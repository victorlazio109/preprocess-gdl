# list tif files in preparation folder.
from pathlib import Path
import argparse
import glob
import re
from preprocess_glob import tile_list_glob
from utils import read_parameters, CsvLogger


def main(glob_params, keep_only='all'):
    images_list = tile_list_glob(**glob_params)
    CsvLog = CsvLogger(out_csv=glob_params['base_dir'] + '/prep_img.csv')
    for img in images_list:
        lst_img = [Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        lst_img.extend([Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.TIF")])
        for elem in lst_img:
            if keep_only == 'all':
                CsvLog.write_row([str(elem)])

            elif keep_only == 'singleband':
                if re.search(rf'*_BAND_*', str(elem.stem)):
                    CsvLog.write_row([str(elem)])

            else:
                if re.search(rf'*_{keep_only}_*', str(elem.stem)):
                    CsvLog.write_row([str(elem)])


if __name__ == '__main__':
    # parser = argparse.ArgumentParser(description='Pansharp execution')
    # parser.add_argument('param_file', metavar='DIR',
    #                     help='Path to preprocessing parameters stored in yaml')
    # args = parser.parse_args()
    # config_path = Path(args.param_file)
    params = read_parameters('/home/valhass/Projects/preprocess-gdl/config.yaml')

    # log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'], keep_only=params['list_img']['keep_only'])
