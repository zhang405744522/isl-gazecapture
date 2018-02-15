from collections import deque
import logging
import socket
import struct

import cv2

import numpy as np


# Length of the buffer we use for reading data.
READ_BUFFER_LENGTH = 8192
# The JPEG magic at the start and end of each frame.
JPEG_MAGIC_START = bytes(b"\xFF\xD8")
JPEG_MAGIC_END = bytes(b"\xFF\xD9")


logger = logging.getLogger(__name__)


class Server(object):
  """ Simple socket server for the online gaze system. """

  class State(object):
    """ Keeps track of the parser state. """

    # Reading the image sequence number.
    READ_IMAGE_SEQ = "ReadImageSeq"
    # Reading the image size.
    READ_IMAGE_SIZE = "ReadImageSize"
    # Reading the first byte of the start magic.
    READ_MAGIC_START_BYTE1 = "ReadMagicStartByte1"
    # Reading the second byte of the start magic.
    READ_MAGIC_START_BYTE2 = "ReadMagicStartByte2"
    # Reading the first byte of the end magic.
    READ_MAGIC_END_BYTE1 = "ReadMagicEndByte1"
    # Reading the second byte of the end magic.
    READ_MAGIC_END_BYTE2 = "ReadMagicEndByte2"

  def __init__(self, port):
    """
    Args:
      port: The port to listen on. """
    self.__init_buffers()

    # A list of complete frames that we have received.
    self.__received_frames = deque()

    self.__listen(port)

  def __init_buffers(self):
    """ Initializes the parser buffers and state. """
    # Contains partial frame data.
    self.__current_frame = bytearray([])
    # Buffer for data read directly from the socket.
    self.__read_buffer = bytearray(b"\x00" * READ_BUFFER_LENGTH)
    # Current state of the parser.
    self.__state = self.State.READ_MAGIC_START_BYTE1

    # The size of the current image we're reading.
    self.__image_size = bytearray(b"\x00" * 4)
    # Remaining bytes of the current image that we have to read.
    self.__size_remaining = -1
    # Current byte we are reading for the image size.
    self.__image_size_index = 0

  def __listen(self, port):
    """ Builds the socket and starts listening for connections.
    Args:
      port: The port to listen on. """
    self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.__sock.bind(("", port))

    # We only want to accept one connection at a time.
    self.__sock.listen(1)

    logger.info("Now listening on port %d." % (port))

  def __extract_frame(self, sequence_num):
    """ Extracts the compressed frame stored in __current_frame,
    and adds it to the __received_frames list. It also clears the
    current_frame array.
    Args:
      sequence_num: The sequence number of the new frame. """
    image = cv2.imdecode(np.asarray(self.__current_frame), cv2.IMREAD_COLOR)
    if image is None:
      # Failed to decode the image.
      logger.warning("Failed to read frame.")

    logger.debug("Got new frame.")
    self.__received_frames.appendleft((image, sequence_num))

    self.__current_frame = bytearray([])

  def __process_new_data(self, size):
    """ Processes a chunk of newly received data.
    Args:
      size: The size of the new chunk of data. """
    # Index of the first byte of the JPEG start sequence.
    jpeg_start_index = 0

    # Look for the JPEG delimiters.
    i = 0
    while i < size:
      byte = self.__read_buffer[i]

      # If we know the image size, we can skip until we get there.
      if self.__size_remaining > 0:
        in_buffer = min(size - i, self.__size_remaining)
        i += in_buffer
        self.__size_remaining -= in_buffer
        continue

      if self.__state == self.State.READ_MAGIC_START_BYTE1:
        # Look for the first byte of the start magic.
        if byte == ord(JPEG_MAGIC_START[0]):
          jpeg_start_index = i
          self.__state = self.State.READ_MAGIC_START_BYTE2

      elif self.__state == self.State.READ_MAGIC_START_BYTE2:
        # Look for the second byte of the start magic.
        if byte == ord(JPEG_MAGIC_START[1]):
          self.__state = self.State.READ_MAGIC_END_BYTE1
        else:
          # The second byte has to come right after the first.
          self.__state = self.State.READ_MAGIC_START_BYTE1

      elif self.__state == self.State.READ_MAGIC_END_BYTE1:
        # Look for the first byte of the end magic.
        if byte == ord(JPEG_MAGIC_END[0]):
          self.__state = self.State.READ_MAGIC_END_BYTE2

        elif self.__size_remaining != -1:
          # This means that our size was invalid. We're going to have to throw
          # this image away and manually search for the start of the next one.
          logger.warning("Lost image framing.")
          self.__current_frame = bytearray([])
          self.__size_remaining = -1
          self.__state = self.State.READ_MAGIC_START_BYTE1

      elif self.__state == self.State.READ_MAGIC_END_BYTE2:
        # Look for the second byte of the end magic.
        if byte == ord(JPEG_MAGIC_END[1]):
          self.__state = self.State.READ_IMAGE_SEQ
          # Save the image data.
          self.__current_frame += self.__read_buffer[jpeg_start_index:(i + 1)]
        else:
          # The second byte has to come right after the first.
          self.__state = self.State.READ_MAGIC_END_BYTE1

      elif self.__state == self.State.READ_IMAGE_SEQ:
        # Read the sequence number of the image.
        self.__state = self.State.READ_IMAGE_SIZE

        # Since we read the sequence number, we can go ahead and extract the
        # image.
        logger.debug("Sequence number: %d" % (byte))
        self.__extract_frame(byte)

      elif self.__state == self.State.READ_IMAGE_SIZE:
        # Read the current size byte of the next image.
        self.__image_size[self.__image_size_index] = byte
        self.__image_size_index += 1

        if self.__image_size_index == 4:
          # We've read everything.
          self.__image_size_index = 0
          self.__state = self.State.READ_MAGIC_END_BYTE1

          # Unpack as an uint32.
          self.__size_remaining = struct.unpack("I", self.__image_size)[0]
          # Subtract 2, because we want to land of the first ending byte.
          self.__size_remaining -= 2
          # Assume that the next image starts directly after this.
          jpeg_start_index = i + 1

      i += 1

    if (self.__state == self.State.READ_MAGIC_END_BYTE1 or
        self.__state == self.State.READ_MAGIC_END_BYTE2):
      # In this case, we got the start of an image, but we didn't finish reading
      # it. Copy what we have from the buffer before we clear it.
      self.__current_frame += self.__read_buffer[jpeg_start_index:size]

  def wait_for_client(self):
    """ Waits until a client connects to the server. """
    logger.info("Waiting for client connection...")

    self.__client, self.__addr = self.__sock.accept()

    logger.info("Got new connection from %s." % (str(self.__addr)))

  def read_next_frame(self):
    """ Gets and returns the next complete JPEG frame from the client.
    Returns:
      The next frame and sequence number, or a None tuple if the client
      disconnected. """
    # Read data from the socket until we have at least one new frame.
    while len(self.__received_frames) == 0:
      logger.debug("Waiting for new data...")
      bytes_read = self.__client.recv_into(self.__read_buffer)
      if bytes_read == 0:
        # Assume client disconnect.
        logger.info("Client %s disconnected." % (str(self.__addr)))
        self.__client.close()

        # Clear the buffers.
        self.__init_buffers()

        return (None, None)

      self.__process_new_data(bytes_read)

    return self.__received_frames.pop()