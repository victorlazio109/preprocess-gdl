import argparse
from pathlib import Path
import logging
import glob
from utils import read_parameters
import os
import re
from preprocess_glob import tile_list_glob
from dataclasses import dataclass
from validation import err_to_table


@dataclass
class ImgError:
    img_name: str
    detected_error: str


def main(glob_params, dry_run=True):
    logging.info("Started")
    # image list.
    pansharp_glob_list = tile_list_glob(**glob_params)
    error_list = []
    num_file_deleted = 0

    for img in pansharp_glob_list:
        err_img = None
        bgrn_dict = {'B': '', 'G': '', 'R': '', 'N': ''}

        # assert that the singleband files are present. Otherwise, do not delete intermediate files.
        lst_img = [Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        lst_img.extend([Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.TIF")])

        lst_to_del = [el for el in lst_img if re.search(r'_BAND_\w+$', str(el.stem)) is None]

        for b in bgrn_dict.keys():
            p = rf"_BAND_{b}"
            try:
                bgrn_dict[b] = [el for el in lst_img if str(el.stem).endswith(p)][0]
            except IndexError:
                err_img = ImgError(img_name=str(img.im_name), detected_error=f"Band {b} is missing.")
                error_list.append(err_img)

        if err_img is None:
            logging.warning(f"Will delete {len(lst_to_del)} files for image {img.im_name}")
            for val in lst_to_del:
                if dry_run:
                    logging.warning(f"Delete file {val}")
                else:
                    try:
                        os.remove(val)
                        num_file_deleted += 1
                    except OSError as e:
                        logging.warning(f"Error: {val} : {e.strerror}")

    if error_list:
        err_to_table(error_list)
    logging.warn(f"Deleted {num_file_deleted} files")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()
    dry_run = not params['process']['delete_intermediate_files']

    main(glob_params=params['glob'], dry_run=dry_run)
