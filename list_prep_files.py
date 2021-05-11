# list tif files in preparation folder.
from pathlib import Path
import argparse
import glob
import re
import dataclasses
import json
from preprocess_glob import tile_list_glob, either
from utils import read_parameters, CsvLogger, get_key_def


def main(glob_params, list_params):
    images_list = tile_list_glob(**glob_params)
    keep_only = list_params['keep_only']
    source_pan = get_key_def('pan', list_params['source'], default=False, expected_type=bool)
    source_mul = get_key_def('mul', list_params['source'], default=False, expected_type=bool)
    prep_band = get_key_def('band', list_params['prep'], default=[], expected_type=list)

    # CsvLog = CsvLogger(out_csv=glob_params['base_dir'] + '/prep_img.csv')
    for img in images_list:
        print(img)
        if source_pan:
            if img.pan_tile_list is not None:
                for pan_img in img.pan_tile_list:
                    print(pan_img)

        # print(img)
        # lst_img = [Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        # lst_img.extend([Path(name) for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.TIF")])
        # for elem in lst_img:
        #     print(elem.stem)
    #         if keep_only == 'all':
    #             print(str(elem.stem))
    #             CsvLog.write_row([str(elem)])
    #
    #         elif keep_only == 'singleband':
    #             if re.search(rf'*_BAND_*', str(elem.stem)):
    #                 CsvLog.write_row([str(elem)])
    #
    #         else:
    #             if f'{keep_only}' in str(elem.stem):
    #                 # print(str(elem.stem))
    #                 CsvLog.write_row([str(elem)])
                # if re.search(''.join(map(either, re.escape(rf'*_{keep_only}_*'))), str(elem.stem)):
                #     print(str(elem.stem))



if __name__ == '__main__':
    # parser = argparse.ArgumentParser(description='Pansharp execution')
    # parser.add_argument('param_file', metavar='DIR',
    #                     help='Path to preprocessing parameters stored in yaml')
    # args = parser.parse_args()
    # config_path = Path(args.param_file)
    params = read_parameters('/home/valhass/Projects/preprocess-gdl/config.yaml')

    # log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'], list_params=params['list_img'])
