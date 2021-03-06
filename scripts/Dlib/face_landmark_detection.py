#!/usr/bin/python
# Based on Dlib example program, copyright below:
#
#
#
# The contents of this file are in the public domain. See LICENSE_FOR_EXAMPLE_PROGRAMS.txt
#
#   This example program shows how to find frontal human faces in an image and
#   estimate their pose.  The pose takes the form of 68 landmarks.  These are
#   points on the face such as the corners of the mouth, along the eyebrows, on
#   the eyes, and so forth.
#
#   This face detector is made using the classic Histogram of Oriented
#   Gradients (HOG) feature combined with a linear classifier, an image pyramid,
#   and sliding window detection scheme.  The pose estimator was created by
#   using dlib's implementation of the paper:
#      One Millisecond Face Alignment with an Ensemble of Regression Trees by
#      Vahid Kazemi and Josephine Sullivan, CVPR 2014
#   and was trained on the iBUG 300-W face landmark dataset.
#
#   Also, note that you can train your own models using dlib's machine learning
#   tools. See train_shape_predictor.py to see an example.
#
#   You can get the shape_predictor_68_face_landmarks.dat file from:
#   http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2
#
# COMPILING/INSTALLING THE DLIB PYTHON INTERFACE
#   You can install dlib using the command:
#       pip install dlib
#
#   Alternatively, if you want to compile dlib yourself then go into the dlib
#   root folder and run:
#       python setup.py install
#   or
#       python setup.py install --yes USE_AVX_INSTRUCTIONS
#   if you have a CPU that supports AVX instructions, since this makes some
#   things run faster.
#
#   Compiling dlib should work on any operating system so long as you have
#   CMake and boost-python installed.  On Ubuntu, this can be done easily by
#   running the command:
#       sudo apt-get install libboost-python-dev cmake
#
#   Also note that this example requires scikit-image which can be installed
#   via the command:
#       pip install scikit-image
#   Or downloaded from http://scikit-image.org/download.html.
import csv
import sys
import os
from os.path import join
import dlib
import glob
from collections import defaultdict
from scipy import misc
import numpy as np
import re
import subprocess
import cv2
import math


class Detector:
    def __init__(self):
        predictor_path = sys.argv[1]
        faces_folder_path = sys.argv[2]

        self.detector = dlib.get_frontal_face_detector()
        self.predictor = dlib.shape_predictor(predictor_path)
        self.threshold = None
        self.num_smoothing = None
        self.win = None

        if '-th' in sys.argv and self.threshold is None:
            self.threshold = float(sys.argv[sys.argv.index('-th') + 1])
        if '-sm' in sys.argv and self.num_smoothing is None:
            self.num_smoothing = int(sys.argv[sys.argv.index('-sm') + 1])
        if '-d' in sys.argv:
            self.distance_weight = float(sys.argv[sys.argv.index('-d') + 1])
        if '-i' in sys.argv:
            self.input = sys.argv[sys.argv.index('-i') + 1]

        arg_dict = {
            '-a': False,
            '-p': False,
            '-c': False,
            '-n': False,
            '-f': 1,
            '-s': False,
            '-sm': False,
            '-sh': False,
            '-i': False,
            '-v': False,
            '-o': False
        }
        for arg in list(arg_dict.keys()):
            if arg in sys.argv:
                arg_dict[arg] = True
        self.all = arg_dict['-a']
        self.pause = arg_dict['-p']
        self.crop = arg_dict['-c']
        self.nose = arg_dict['-n']
        self.fps_frac = arg_dict['-f']
        self.save = arg_dict['-s']
        self.smooth = arg_dict['-sm']
        self.show = arg_dict['-sh']
        self.verbose = arg_dict['-v']
        self.override = arg_dict['-o']

        if self.show:
            self.win = dlib.image_window()

        self.nose_txt_files = None
        self.nose_path = None
        self.crop_txt_files = None

        if self.nose:
            self.nose_path = sys.argv[sys.argv.index('-n') + 1]
            self.nose_txt_files = self.find_txt_files(self.nose_path)

        if self.crop:
            self.crop_path = sys.argv[sys.argv.index('-c') + 1]
            self.crop_txt_files = self.find_txt_files(self.crop_path)

        file_types = ['*.jpg', '*.png']
        files = []
        for ext in file_types:
            files.extend(glob.glob(join(faces_folder_path + '/**/', ext), recursive=True))
        files = sorted([f for f in files if '_detected' not in f])
        out_writer = None
        if self.override:
            out_writer = csv.writer(open(os.path.join(faces_folder_path, str(self.threshold) + 'out.csv'), 'w'))
            self.ref_dict = self.open_csv_file(os.path.join(faces_folder_path, 'cb46fd46_5_coordinates.csv'))
            self.ref_indexes = list(self.ref_dict.keys())
            self.optim_dict = defaultdict()
        crop_im_file = os.path.join(faces_folder_path, 'crop_im_arr.npy')
        if os.path.isfile(crop_im_file):
            self.crop_im_arr_arr = np.load(crop_im_file)
        else:
            self.crop_im_arr_arr = np.array([
                self.crop_predictor(img, f, scaled_height=img.shape[0], scaled_width=img.shape[1]) for img, f in
                zip(self.make_img_arr(files), files) if img is not None and f is not None])
            np.save(crop_im_file, self.crop_im_arr_arr)
        self.scores_dict_arr = {index: self.show_face(f, crop_im_array[0], detected=False, show=False) for
                                index, (f, crop_im_array) in
                                enumerate(zip(files, self.crop_im_arr_arr)) if
                                f is not None and crop_im_array is not None}

        # for thresh in np.arange(-.8, .5, .2):
        for distance_weight in np.arange(1, 6, 1):
            for num_smoothing in np.arange(1, 15, 3):
                std_devs = []
                # self.threshold = self.threshold
                if self.override:
                    self.distance_weight = distance_weight
                    self.num_smoothing = num_smoothing
                out_str = os.path.join(vid_path, 'thresh_' + str(
                    self.threshold).replace('.', '') + 'dis_' + str(
                    self.distance_weight).replace('.',
                                                  '') + 'num_smoothing' + str(
                    self.num_smoothing).replace('.',
                                                ''))
                # Preload predictions for each frame
                self.max_score_arr = {index: self.find_maxes(scores_dict) for index, scores_dict in
                                      self.scores_dict_arr.items() if scores_dict}
                percent_found = len(
                    [i for i in self.max_score_arr.keys() if self.max_score_arr[i] != (None, None)]) / len(
                    self.max_score_arr.keys())
                for index, (max_score, max_d) in self.max_score_arr.items():
                    crop_im_arr = self.crop_im_arr_arr[index]
                    if crop_im_arr is not None:
                        x_min = crop_im_arr[1]
                        y_min = crop_im_arr[2]
                        x_max = crop_im_arr[3]
                        y_max = crop_im_arr[4]
                    if max_score is not None:
                        old_top = max_d.top()
                        old_left = max_d.left()
                        old_right = max_d.right()
                        old_bottom = max_d.bottom()
                        new_top = int(old_top + y_min)
                        new_left = int(old_left + x_min)
                        new_right = int(old_right + x_min)
                        new_bottom = int(old_bottom + y_min)
                        new_d = dlib.rectangle(left=new_left, top=new_top, right=new_right,
                                               bottom=new_bottom)
                        self.max_score_arr[index] = (max_score, new_d)
                self.shape_arr = {index: self.make_shape(score, image, d, show=False, save=False) for
                                  image, (index, (score, d))
                                  in zip(self.make_img_arr(files), self.max_score_arr.items()) if
                                  image is not None and score is not None and d is not None}

                for index, f in enumerate(files):
                    if self.verbose:
                        print("Processing file: {}".format(f))
                    num_smoothing = self.num_smoothing
                    img = misc.imread(f, mode='RGB')
                    img = misc.imresize(img, (960, 1280))
                    scaled_width = img.shape[1]
                    scaled_height = img.shape[0]
                    curr_im_index = None
                    detected = False
                    if self.win:
                        self.win.clear_overlay()
                        self.win.set_image(img)
                    if self.smooth:
                        if self.nose and self.crop:
                            crop_im_arr_arr = self.make_range_arr(big_arr=self.crop_im_arr_arr, index=index,
                                                                  num_smoothing=num_smoothing)
                            f_arr = self.make_range_arr(files, index, num_smoothing)
                            crop_im_arr = self.crop_im_arr_arr[index]
                            if crop_im_arr is not None:
                                crop_im = crop_im_arr[0]
                                if crop_im is not None and f_arr is not None and crop_im_arr_arr is not None:
                                    max_score_arr = self.make_range_arr(self.max_score_arr, index, num_smoothing,
                                                                        dict=True)
                                    shape_arr = self.make_range_arr(self.shape_arr, index, num_smoothing, dict=True)
                                    if max_score_arr:
                                        shape = self.show_average_face(f, img, index, max_score_arr, shape_arr,
                                                                       show=self.show)
                                        if self.override:
                                            closest_ind = self.find_nearest(self.ref_indexes, index / 30)
                                            ref_arr = [(arr[0], arr[1]) for arr in self.ref_dict[closest_ind]]
                                            if shape:
                                                diff_arr = [self.find_distance(x1, x2, y1, y2) for (x1, y1), (x2, y2)
                                                            in zip(ref_arr, shape)]
                                                ref_score = np.average(diff_arr)
                                                std_devs.append(ref_score)

                            else:
                                dir_name, base_name, split_name = self.splitname(f)
                                new_name = self.new_file_name(os.path.join(dir_name, 'detected/'), split_name,
                                                              '_detected')
                                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                                cv2.imwrite(new_name, img)
                        else:
                            self.show_face(f, img, detected)
                    else:
                        if self.nose and self.crop:
                            crop_im_arr = self.crop_predictor(img, f, scaled_height=scaled_height,
                                                              scaled_width=scaled_width)
                            if crop_im_arr is not None:
                                crop_im = crop_im_arr[0]
                                x_min = crop_im_arr[1]
                                y_min = crop_im_arr[2]
                                x_max = crop_im_arr[3]
                                y_max = crop_im_arr[4]
                                scores_dict = self.show_face(f, crop_im, detected, show=False)

                                if not self.all:
                                    max_score, max_d = self.find_maxes(scores_dict)
                                    if max_score is not None:
                                        old_top = max_d.top()
                                        old_left = max_d.left()
                                        old_right = max_d.right()
                                        old_bottom = max_d.bottom()
                                        self.win.set_image(img)
                                        new_top = int(old_top + y_min)
                                        new_left = int(old_left + x_min)
                                        new_right = int(old_right + x_min)
                                        new_bottom = int(old_bottom + y_min)
                                        new_d = dlib.rectangle(left=new_left, top=new_top, right=new_right,
                                                               bottom=new_bottom)
                                        self.show_best_face(name=f, scores_dict=scores_dict, img=img, show=True,
                                                            max_score=max_score, max_d=new_d, save=True)


                            else:
                                dir_name, base_name, split_name = self.splitname(f)
                                new_name = self.new_file_name(os.path.join(dir_name, 'detected/'), split_name,
                                                              '_detected')
                                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                                cv2.imwrite(new_name, img)
                        else:
                            self.show_face(f, img, detected)
                if self.override:
                    ave = np.average(std_devs)
                    self.optim_dict[ave] = out_str
                    print(out_str + " Score: " + str(ave))
                    out_writer.writerow(
                        [str(ave), str(self.optim_dict[ave]), self.threshold, percent_found])
                elif not self.override:
                    self.send_to_ffmpeg(out_str)
                    break
                else:
                    # TODO: Check if legit
                    for image, (index, (score, d)) in zip(self.make_img_arr(files), self.max_score_arr.items()):
                        if image is not None and score is not None and d is not None:
                            dir_name, basename, split_name = self.splitname(image)
                            new_name = self.new_file_name(os.path.join(dir_name, 'detected/'), split_name,
                                                          '_detected')
                            self.mark_im(misc.imresize(cv2.imread(files[index]), (960, 1280)), d, new_name,
                                         self.shape_arr[index])
                    self.send_to_ffmpeg(out_str)

                    # for score in sorted(self.optim_dict.keys()):
                    #   out_writer.writerow([str(score)] + self.optim_dict[score])
            # TODO: Fix breaking, abstract loops out
            if not self.override:
                break

    def overlay(self, shape, d):
        if self.win:
            self.win.add_overlay(shape)
            self.win.add_overlay(d)

    @staticmethod
    def send_to_ffmpeg(out_str):
        subprocess.Popen("ffmpeg -r 30 -f image2 -s 1920x1080 -pattern_type glob -i '{0}' "
                         "-b 2000k {1}".format('*.png',
                                               out_str + '.mp4'),
                         cwd=detected_path,
                         shell=True).wait()

    @staticmethod
    def splitname(name):
        dir_name = os.path.dirname(name)
        base_name = os.path.basename(name)
        split_name = os.path.splitext(base_name)
        return dir_name, base_name, split_name

    @staticmethod
    def find_crop_path(file, crop_txt_files):
        parts = file.split('.')
        pid = parts[0]
        try:
            back_half_name = ''.join(parts[1][parts[1].index('out') + 3: len(parts[1])])
            out_num = int(re.sub("[^0-9]", "", back_half_name))
        except ValueError:
            return None
        out_file = None
        if pid in list(crop_txt_files.keys()):
            out_file = crop_txt_files[pid]
        return out_file, out_num

    @staticmethod
    def find_distance(x1, x2, y1, y2):
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    @staticmethod
    def find_nearest(array, value):
        sub_array = [i - value for i in array]
        idx = (np.abs(sub_array)).argmin()
        return array[idx]

    def make_read_arr(self, f, num_constraint=None):
        readArr = f.readlines()
        if num_constraint is not None:
            readArr = [readArr[i].split(',')[0:num_constraint] for i in range(0, len(readArr), self.fps_frac)]
        else:
            readArr = [readArr[i].split(',') for i in range(0, len(readArr), self.fps_frac)]
        for index, num in enumerate(readArr):
            for val_index, val in enumerate(num):
                readArr[index][val_index] = val.replace('(', '')
                val = readArr[index][val_index]
                readArr[index][val_index] = val.replace(')', '')
        readArr = [[float(k) for k in i] for i in readArr]
        return readArr

        # Sets coordinates based on CSV

    def open_csv_file(self, path):
        with open(path, 'rt') as csvfile:
            reader = csv.reader(csvfile)
            all_rows = [i for i in reader]
            for row in all_rows:
                for i in range(2, len(row), 3):
                    if row[i] == "":
                        row[i] = -1
                    if row[i + 1] == "":
                        row[i + 1] = -1
            file_dict = {index: [[abs(float(row[i])), abs(float(row[i + 1]))] for i in range(2, len(row), 3)] for
                         index, row in
                         enumerate(all_rows) if index >= 1}
            for index, row in enumerate(all_rows):
                if index in list(file_dict.keys()):
                    while len(file_dict[index]) < 68:
                        file_dict[index].append([0, 0])
            return file_dict

    @staticmethod
    def make_range_arr(big_arr, index, num_smoothing, dict=False):
        if dict:
            return {(index + i): big_arr[(index + i)] for i in
                    range(-num_smoothing, num_smoothing + 1) if
                    (index + i) in big_arr.keys()}
        else:
            return np.array([big_arr[i] for i in
                             range(-num_smoothing, num_smoothing) if
                             (index + i) in range(0, len(big_arr))])

    def crop_predictor(self, img, name, scaled_width, scaled_height):
        print('Name: {0}'.format(name))
        base_name = os.path.basename(name)
        crop_file_path, file_num = self.find_crop_path(base_name, self.crop_txt_files)
        print('Crop file: {0}'.format(crop_file_path))
        x_min = 0
        y_min = 0
        x_max = 0
        y_max = 0
        if crop_file_path is not None:
            f = open(crop_file_path)
            read_arr = self.make_read_arr(f)
            i = file_num - 1
            if len(read_arr) > i:
                curr_im_coords = read_arr[i]
                x_min = curr_im_coords[0] * scaled_width / 640
                y_min = curr_im_coords[2] * scaled_height / 480
                x_max = curr_im_coords[1] * scaled_width / 640
                y_max = curr_im_coords[3] * scaled_height / 480

        nose_file_path, file_num = self.find_crop_path(base_name, self.nose_txt_files)
        print('Nose file: {0}'.format(nose_file_path))
        if nose_file_path is not None:
            f = open(nose_file_path)
            read_arr = self.make_read_arr(f, 3)

            i = file_num - 1
            if len(read_arr) > i:
                confidence = read_arr[i][2]
                print('Crop Confidence: {0}'.format(confidence))
                if confidence > .25:
                    x_center = read_arr[i][0]
                    y_center = read_arr[i][1]
                    norm_coords = self.normalize_to_camera([(x_center, y_center)], [x_min, x_max, y_min, y_max],
                                                           scaled_width=scaled_width, scaled_height=scaled_height)
                    x_center = norm_coords[0][0]
                    y_center = norm_coords[0][1]
                    bb_size = 100
                    x_min = int(x_center - bb_size)
                    y_min = int(y_center - bb_size)
                    x_max = int(x_center + bb_size)
                    y_max = int(y_center + bb_size)
                    im = img
                    x_coords = np.clip(np.array([x_min, x_max]), 0, im.shape[0])
                    y_coords = np.clip(np.array([y_min, y_max]), 0, im.shape[1])
                    x_min = x_coords[0]
                    x_max = x_coords[1]
                    y_min = y_coords[0]
                    y_max = y_coords[1]
                    crop_im = im[y_coords[0]:y_coords[1], x_coords[0]:x_coords[1]].copy()
                    return [crop_im, x_min, y_min, x_max, y_max]

    @staticmethod
    def normalize_to_camera(coords, crop_coord, scaled_width, scaled_height):
        if sum(crop_coord) <= 0:
            rescale_factor = (scaled_width / 256, scaled_height / 256)  # Original size was 256
        else:
            rescale_factor = ((crop_coord[1] - crop_coord[0]) / 256.0, (crop_coord[3] - crop_coord[2]) / 256.0)
        norm_coords = [
            np.array((coord[0] * rescale_factor[0] + crop_coord[0], coord[1] * rescale_factor[1] + crop_coord[2]))
            for coord in coords]
        return np.array(norm_coords)

    @staticmethod
    def new_file_name(dir_name, split_name, addition):
        return os.path.join(dir_name, split_name[0] + addition + split_name[1])

    def show_average_face(self, name, img, curr_index, scores_dict, shape_arr, show=False):
        # Normalize Scores
        norm_scores = {i: ((scores_dict[i][0] + 1) / 2) for i in list(scores_dict.keys()) if
                       scores_dict[i][0] is not None}
        # change scores by half distance from center
        # norm_scores = {index: score / ((1 / self.distance_weight) * (abs(index - curr_index) + 1)) for index, score in
        #               norm_scores.items()}
        # Change scores to be a Gaussian distribution
        gauss = np.random.normal(0, 1 / self.distance_weight, len((norm_scores.keys())))
        # Multiply the scores to the Gaussian function, other option is to add them
        norm_scores = {key: norm_scores[key] * gauss[index] for index, key in enumerate(norm_scores.keys())}

        d_arr = [scores_dict[i][1] for i in list(norm_scores.keys())]
        x_arr = [[shape_arr[j].part(i).x for i in range(shape_arr[j].num_parts)] for j in list(norm_scores.keys())]
        y_arr = [[shape_arr[j].part(i).y for i in range(shape_arr[j].num_parts)] for j in list(norm_scores.keys())]
        score_arr = [norm_scores[i] for i in list(norm_scores.keys())]
        if score_arr:
            average_x_arr = np.average(x_arr, axis=0, weights=score_arr).astype(int)
            average_y_arr = np.average(y_arr, axis=0, weights=score_arr).astype(int)

            left_arr = np.array([d.left() for d in d_arr])
            top_arr = np.array([d.top() for d in d_arr])
            right_arr = np.array([d.right() for d in d_arr])
            bottom_arr = np.array([d.bottom() for d in d_arr])
            average_left = np.average(left_arr, weights=score_arr).astype(int)
            average_top = np.average(top_arr, weights=score_arr).astype(int)
            average_right = np.average(right_arr, weights=score_arr).astype(int)
            average_bottom = np.average(bottom_arr, weights=score_arr).astype(int)

            dir_name, basename, split_name = self.splitname(name)
            new_name = self.new_file_name(os.path.join(dir_name, 'detected/'), split_name,
                                          '_detected')
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            box = cv2.rectangle(img, (average_left, average_top), (average_right, average_bottom), color=(255, 0, 0))
            x_y_arr = zip(average_x_arr, average_y_arr)
            if self.override:
                self.mark_im(img, None, new_name, None, x_y_arr, box, show)
            return list(zip(average_x_arr, average_y_arr))

    def show_best_face(self, name, scores_dict, img, show=True, max_score=None, max_d=None, save=False):
        if max_score is None and max_d is None:
            max_score, max_d = self.find_maxes(scores_dict)
        if max_score is not None:
            max_i = scores_dict[max_score][1]
            face_type = scores_dict[max_score][2]
            shape = None
            print("Detection {}, score: {}, face_type:{}".format(
                max_d, max_score, max_i))
            self.make_shape(max_score, img, max_d, show, save, name=name)

    def make_shape(self, max_score, img, max_d, show, save, name=None):
        if self.threshold is not None and max_score is not None and max_score > self.threshold:
            shape = self.predictor(img, max_d)
            if self.verbose:
                print("Left: {} Top: {} Right: {} Bottom: {}".format(max_d.left(), max_d.top(), max_d.right(),
                                                                     max_d.bottom()))
            # Draw the face landmarks on the screen.
            if show:
                self.overlay(shape, max_d)
            if self.pause:
                dlib.hit_enter_to_continue()
            if save and self.save:
                self.save_im(name, shape, max_d, scale=True)
            return shape

    def save_im(self, name, shape, d, scale):
        img = cv2.imread(name)
        img = misc.imresize(img, (960, 1280))
        dir_name, basename, split_name = self.splitname(name)
        new_name = self.new_file_name(os.path.join(dir_name, 'detected/'), split_name, '_detected')
        self.mark_im(img, d, new_name, shape)

    def mark_im(self, img, d, new_name, shape=None, x_y_arr=None, box=None, show=False):
        if box is None:
            box = cv2.rectangle(img, (d.left(), d.top()), (d.right(), d.bottom()), color=(255, 0, 0))
        if shape is not None:
            for i in range(shape.num_parts):
                dot = shape.part(i)
                cv_dot = cv2.circle(img, (dot.x, dot.y), 3, (0, 0, 255))
        elif x_y_arr is not None:
            cv_dot_arr = [cv2.circle(img, (dot[0], dot[1]), 3, (0, 0, 255)) for dot in x_y_arr]
        cv2.imwrite(new_name, img[100:800, 300:800])  # Saves cropped image, change cropping dimensions if necessary
        if show:
            self.win.set_image(misc.imresize(misc.imread(new_name, mode='RGB'), (960, 1280)))

    @staticmethod
    def make_img_arr(files):
        img_arr = (misc.imread(file, mode='RGB') for file in files)
        img_arr = (misc.imresize(img, (960, 1280)) for img in img_arr)
        return img_arr

    def show_face(self, name, img, detected, show=True):
        if show and self.win:
            self.win.set_image(img)
        dets, scores, idx = self.detector.run(img, 1, -1)
        scores_dict = defaultdict()
        if self.verbose:
            print("Number of faces detected: {}".format(len(dets)))

        for i, d in enumerate(dets):
            score = scores[i]
            scores_dict[score] = [d, i, idx[i]]
            if show:
                if self.all:
                    if score > self.threshold:
                        print("Detection: {}, score: {}, face_type:{}".format(d, score, idx[i]))
                        shape = self.predictor(img, d)
                        print("Left: {} Top: {} Right: {} Bottom: {}".format(d.left(), d.top(), d.right(), d.bottom()))
                        self.overlay(shape, d)
                        detected = True
        if detected and self.pause:
            dlib.hit_enter_to_continue()

        if show and not self.all and self.show:
            self.win.set_image(img)
            self.show_best_face(name, scores_dict, img=img)

        return scores_dict

    def find_maxes(self, scores_dict):
        try:
            max_score = max(list(scores_dict.keys()))
        except:
            return None, None
        if max_score > self.threshold:
            max_d = scores_dict[max_score][0]
            return max_score, max_d
        else:
            return None, None

    @staticmethod
    def write_to_im(new_name, img):
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        cv2.imwrite(new_name, img)

    @staticmethod
    def find_txt_files(path):
        return {os.path.splitext(os.path.basename(v))[0]: v for v in
                glob.iglob(os.path.join(path + '/**/*.txt'), recursive=True)}


if __name__ == '__main__':
    faces_folder_path = sys.argv[2]
    detected_path = os.path.join(faces_folder_path, "detected/")
    vid_path = os.path.join(detected_path, "videos/")
    det = Detector()
