# list tif files in preparation folder.
from pathlib import Path
import argparse
import glob
from preprocess_glob import tile_list_glob
from utils import read_parameters


def main(glob_params):
    images_list = tile_list_glob(**glob_params)
    lst_files = []
    for img in images_list:
        lst_img = [Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        lst_img.extend([Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.TIF")])
        lst_files.extend(lst_img)
    print(lst_files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'])
