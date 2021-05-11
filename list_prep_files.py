# list tif files in preparation folder.
from pathlib import Path
import argparse
import glob
import re
import dataclasses
import json
from preprocess_glob import tile_list_glob, either
from utils import read_parameters, CsvLogger, get_key_def

all_dict = {'all_images': []}


def main(glob_params, list_params):
    images_list = tile_list_glob(**glob_params)
    keep_only = list_params['keep_only']
    source_pan = get_key_def('pan', list_params['source'], default=False, expected_type=bool)
    source_mul = get_key_def('mul', list_params['source'], default=False, expected_type=bool)
    prep_band = get_key_def('band', list_params['prep'], default=[], expected_type=list)

    # CsvLog = CsvLogger(out_csv=glob_params['base_dir'] + '/prep_img.csv')
    for img in images_list:
        data_struct = {'sensorID': '',
                       'pan_img': [],
                       'mul_img': [],
                       'r_band': '',
                       'g_band': '',
                       'b_band': '',
                       'nir_band': '',
                       'gpkg': ''}
        data_struct['sensorID'] = img.im_name
        if source_pan:
            if img.pan_tile_list is not None:
                for pan_img in img.pan_tile_list:
                    data_struct['pan_img'].append(pan_img)

        if source_mul:
            if img.mul_tile_list is not None:
                for mul_img in img.mul_tile_list:
                    data_struct['mul_img'].append(mul_img)



        all_dict['all_images'].append(data_struct)
    print(all_dict)

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
