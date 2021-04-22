import argparse
from pathlib import Path
import logging
import glob
from utils import read_parameters
import os
from preprocess_glob import tile_list_glob
from dataclasses import dataclass


@dataclass
class ImgError:
    img_name: str
    detected_error: str


def main(glob_params):
    # image list.
    pansharp_glob_list = tile_list_glob(**glob_params)
    error_list = []

    for img in pansharp_glob_list:
        err_img = None
        bgrn_dict = {'B': '', 'G': '', 'R': '', 'N': ''}

        # assert that the singleband files are present. Otherwise, do not delete intermediate files.
        lst_img = [Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        lst_img.extend([Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.TIF")])
        for b in bgrn_dict.keys():
            p = rf"_BAND_{b}.tif"
            try:
                bgrn_dict[b] = [el for el in lst_img if el.endswith(p)][0]
            except IndexError:
                err_img = ImgError(img_name=str(img.im_name), detected_error=f"Band {b} is missing.")
                error_list.append(err_img)

        if err_img is None:
            for key, val in bgrn_dict.items():
                lst_img.remove(val)
            logging.warning(f"Will delete {len(lst_img)} files for image {img.im_name}")
            for file in lst_img:
                try:
                    os.remove(file)
                except OSError as e:
                    print("Error: %s : %s" % (file, e.strerror))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'])
