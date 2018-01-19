#!/usr/bin/python


import argparse

import json
import os
import shutil

import cv2


def extract_crop_data(crop_info):
  """ Extracts the crop bounding data from the raw structure.
  Args:
    crop_info: The raw crop data structure.
  Returns:
    The x and y coordinates of the top left corner, and width and height of
    the crop, and whether the crop is valid. """
  x_crop = crop_info["X"]
  y_crop = crop_info["Y"]
  w_crop = crop_info["W"]
  h_crop = crop_info["H"]
  crop_valid = crop_info["IsValid"]

  return x_crop, y_crop, w_crop, h_crop, crop_valid

def extract_eye_crops(images, face_data, left_eye_data):
  """ Extract the eye crop from an image.
  Args:
    images: A list of images to process.
    left_eye_data: The crop data for the left eye.
    face_data: The crop data for the face.
  Returns:
    A cropped version of the images. """
  face_x = face_data['X']
  face_y = face_data['Y']

  eye_x = left_eye_data['X']
  eye_y = left_eye_data['Y']
  eye_w = left_eye_data['W']
  eye_h = left_eye_data['H']

  crops = []
  for fx, fy, ex, ey, ew, eh, image in zip(face_x, face_y, eye_x,
                                           eye_y, eye_w, eye_h, images):
    # First, get the global eye crop position.
    global_x = int(fx + ex)
    global_y = int(fy + ey)
    end_x = int(global_x + ew)
    end_y = int(global_y + eh)

    # Now, crop the image.
    crop = image[global_y:end_y, global_x:end_x]
    if not crop.shape[0]:
      # Still add it as a placeholder.
      crops.append(crop)
      continue

    # Resize the crop.
    crop = reshape_image(crop, (60, 36))
    crops.append(crop)

  return crops

def extract_face_crops(images, face_data):
  """ Extract the face crop from an image.
  Args:
    images: A list of the images to process.
    face_data: The crop data for the face.
  Returns:
    A cropped version of the images, in the same order. A None value in this
    list indicates a face crop that was not valid. """
  face_x, face_y, face_w, face_h, face_valid = extract_crop_data(face_data)
  crops = []

  for i in range(0, len(images)):
    if not face_valid[i]:
      # Face crop is invalid.
      crops.append(None)
      continue

    start_x = int(face_x[i])
    end_x = start_x + int(face_w[i])
    start_y = int(face_y[i])
    end_y = start_y + int(face_h[i])

    # Crop the image.
    crop = images[i][start_y:end_y, start_x:end_x]
    crops.append(crop)

  return crops

def reshape_image(image, shape, offset=(0, 0)):
  """ Reshapes a stored image so that it is a consistent shape and size.
  Args:
    image: The image to reshape.
    shape: The shape we want the image to be.
    offset: An optional offset. This can be used to direct it not to crop to the
            center of the image. In the tuple, the horizontal offset comes
            before the vertical one.
  Returns:
    The reshaped image.
  """
  # Crop the image to just the center square.
  if len(image.shape) == 3:
    # It may have multiple color channels.
    height, width, _ = image.shape
  else:
    height, width = image.shape

  target_width, target_height = shape

  # Find the largest we can make the initial crop.
  multiplier = 1
  if width > target_width:
    multiplier = width / target_width
  elif height > target_height:
    multiplier = height / target_height
  target_width *= multiplier
  target_height *= multiplier

  crop_width = target_width
  crop_height = target_height
  # Our goal here is to keep the same aspect ratio as the original.
  if width <= target_width:
    # We need to reduce the width for our initial cropping.
    crop_width = width
    crop_height = target_height * (float(crop_width) / target_width)
  if height <= target_height:
    # We need to reduce the height for our initial cropping.
    crop_height = height
    crop_width = target_width * (float(crop_height) / target_height)

  crop_width = int(crop_width)
  crop_height = int(crop_height)

  # Crop the image.
  crop_left = (width - crop_width) / 2
  crop_top = (height - crop_height) / 2

  # Account for the crop offset.
  offset_left, offset_top = offset
  crop_left += offset_left
  crop_top += offset_top
  # Bound it in the image.
  crop_left = max(0, crop_left)
  crop_left = min(width - 1, crop_left)
  crop_top = max(0, crop_top)
  crop_top = min(height - 1, crop_top)

  image = image[crop_top:(crop_height + crop_top),
                crop_left:(crop_width + crop_left)]

  # Set a proper size, which should just be directly scaling up or down.
  image = cv2.resize(image, shape)

  return image

def generate_names(dot_info, grid_info, left_eye_info, right_eye_info,
                   session):
  """ Generates names for a set of images that match our existing data from Zac.
  Args:
    dot_info: The loaded dot information.
    grid_info: The loaded face grid information.
    left_eye_info: The loaded left eye crop information.
    right_eye_info: The loaded right eye crop information.
    face_grid: The loaded face grid information.
    session: The name of the session.
  Returns:
    A list of generated names. Names will be None if the data is not valid. """
  # Location of the dot.
  x_cam = dot_info["XCam"]
  y_cam = dot_info["YCam"]

  # Crop coordinates and sizes.
  x_leye, y_leye, w_leye, h_leye, leye_valid = extract_crop_data(left_eye_info)
  x_reye, y_reye, w_reye, h_reye, reye_valid = extract_crop_data(right_eye_info)
  # Face grid coordinates and sizes.
  x_face, y_face, w_face, h_face, face_valid = extract_crop_data(grid_info)


  names = []
  for i in range(0, len(x_cam)):
    # Check if the frame is valid.
    if not (face_valid[i] and leye_valid[i] and reye_valid[i]):
      names.append(None)
      continue

    # Generate a name for the frame.
    name = "gazecap_%s_f%d_%f_%f_%d_%d_%d_%d_%f_%f_%f_%f_%f_%f_%f_%f.jpg" % \
            (session, i, x_cam[i], y_cam[i], x_face[i], y_face[i], w_face[i],
             h_face[i], x_leye[i], y_leye[i], w_leye[i], h_leye[i], x_reye[i],
             y_reye[i], w_reye[i], h_reye[i])
    names.append(name)

  return names

def save_images(frames, names, outdir):
  """ Copies the processed images to an output directory, with the correct
  names.
  Args:
    frames: The processed frames.
    names: The generated names for the frames, in order.
    outdir: The name of the directory to copy the frames to. """
  for frame, new_name in zip(frames, names):
    if new_name is None:
      # This means that the frame is invalid.
      continue

    out_path = os.path.join(outdir, new_name)
    cv2.imwrite(out_path, frame)

def load_images(frame_dir, frame_info):
  """ Loads images from the frame directory.
  Args:
    frame_dir: The directory to load images from.
    frame_info: The list of frame names. """
  images = []

  for frame in frame_info:
    frame_path = os.path.join(frame_dir, frame)

    image = cv2.imread(frame_path)
    if image is None:
      raise RuntimeError("Failed to read image: %s" % (frame_path))
    images.append(image)

  return images

def process_session(session_dir, out_dir):
  """ Process a session worth of data.
  Args:
    session_dir: The directory of the session.
    out_dir: The output directory to copy the images to.
  Returns:
    The eye crops for the session, along with the corresponding names. """
  session_name = session_dir.split("/")[-1]
  print "Processing session %s..." % (session_name)

  # Load all the relevant metadata.
  leye_file = file(os.path.join(session_dir, "appleLeftEye.json"))
  leye_info = json.load(leye_file)
  leye_file.close()

  reye_file = file(os.path.join(session_dir, "appleRightEye.json"))
  reye_info = json.load(reye_file)
  reye_file.close()

  face_file = file(os.path.join(session_dir, "appleFace.json"))
  face_info = json.load(face_file)
  face_file.close()

  dot_file = file(os.path.join(session_dir, "dotInfo.json"))
  dot_info = json.load(dot_file)
  dot_file.close()

  grid_file = file(os.path.join(session_dir, "faceGrid.json"))
  grid_info = json.load(grid_file)
  grid_file.close()

  frame_file = file(os.path.join(session_dir, "frames.json"))
  frame_info = json.load(frame_file)
  frame_file.close()

  # Generate image names.
  names = generate_names(dot_info, grid_info, leye_info, reye_info,
                         session_name)

  # Load images and crop faces.
  frame_dir = os.path.join(session_dir, "frames")
  frames = load_images(frame_dir, frame_info)
  face_crops = extract_face_crops(frames, face_info)

  # Copy images.
  save_images(face_crops, names, out_dir)

def process_dataset(dataset_dir, output_dir, start_at=None):
  """ Processes an entire dataset, one session at a time.
  Args:
    dataset_dir: The root dataset directory.
    output_dir: Where to write the output images.
    start_at: Session to start at. """
  # Create output directory.
  if os.path.exists(output_dir):
    # Remove existing direcory if it exists.
    print "Removing existing directory '%s'." % (output_dir)
    shutil.rmtree(output_dir)
  os.mkdir(output_dir)

  # Process each session one by one.
  process = False
  for item in os.listdir(dataset_dir):
    if (start_at and item == start_at):
      # We can start here.
      process = True
    if (start_at and not process):
      continue

    item_path = os.path.join(dataset_dir, item)
    if not os.path.isdir(item_path):
      # This is some extraneous file.
      continue

    process_session(item_path, output_dir)

def main():
  parser = argparse.ArgumentParser("Convert the GazeCapture dataset.")
  parser.add_argument("dataset_dir", help="The root dataset directory.")
  parser.add_argument("output_dir",
                      help="The directory to write output images.")
  parser.add_argument("-s", "--start_at", default=None,
                      help="Specify a session to start processing at.")
  args = parser.parse_args()

  process_dataset(args.dataset_dir, args.output_dir, args.start_at)

if __name__ == "__main__":
  main()