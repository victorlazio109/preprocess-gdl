import glob
import re
import json
import argparse
import logging
from tqdm import tqdm
from pathlib import Path
from preprocess_glob import tile_list_glob
from utils import read_parameters, get_key_def

logging.getLogger(__name__)
logging.basicConfig(filename='logs/prep_glob.log', level=logging.DEBUG)
all_dict = {'all_images': []}
pattern = "([a-zA-Z]+)([0-9]+)"


def main(glob_params, list_params):
    images_list = tile_list_glob(**glob_params)
    source_pan = get_key_def('pan', list_params['source'], default=False, expected_type=bool)
    source_mul = get_key_def('mul', list_params['source'], default=False, expected_type=bool)
    prep_band = get_key_def('band', list_params['prep'], default=[], expected_type=list)
    geopackage = glob.glob(get_key_def('gpkg', list_params, default='', expected_type=str))
    out_pth = get_key_def('output_file', list_params, default='data_file.json', expected_type=str)

    for img in tqdm(images_list, desc="crawling images"):
        data_struct = {'sensorID': '',
                       'pan_img': [],
                       'mul_img': [],
                       'R_band': '',
                       'G_band': '',
                       'B_band': '',
                       'N_band': '',
                       'gpkg': ''}
        data_struct['sensorID'] = img.im_name
        if geopackage:
            for gpkg in geopackage:
                A = re.split(pattern, Path(gpkg).stem.replace('_', ""))
                B = re.split(pattern, f'{img.image_folder.parent.name}'.replace("_", ""))[:len(A)]
                if set(A).issubset(set(B)):
                    data_struct['gpkg'] = gpkg

        if source_pan:
            if img.pan_tile_list is not None:
                for pan_img in img.pan_tile_list:
                    data_struct['pan_img'].append(str(pan_img))

        if source_mul:
            if img.mul_tile_list is not None:
                for mul_img in img.mul_tile_list:
                    data_struct['mul_img'].append(str(mul_img))

        if prep_band:
            if set(prep_band).issubset({'R', 'G', 'B', 'N'}):
                for i_b in prep_band:
                    path = list((img.parent_folder / img.image_folder / img.prep_folder).glob(f'*uint8_BAND_{i_b}.tif'))
                    if path:
                        data_struct[f'{i_b}_band'] = str(path[0])
                    else:
                        logging.warn(f'There are no compatible {i_b} band uint8 image found in {img.prep_folder}')
            else:
                logging.warn(f'There are no compatible image bands defined')

        all_dict['all_images'].append(data_struct)

    with open(out_pth, 'w') as fout:
        json.dump(all_dict, fout, indent=4)

    print('\n\nProcess Completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(config_path)

    # log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'], list_params=params['list_img'])