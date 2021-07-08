import glob
import re
import json
import argparse
import logging
import xml.etree.ElementTree as ET
from tqdm import tqdm
from pathlib import Path
from preprocess_glob import tile_list_glob
from utils import read_parameters, get_key_def
from typing import List

logging.getLogger(__name__)
logging.basicConfig(filename='logs/crawl.log', level=logging.WARNING)
all_dict = {'all_images': []}


def get_band_order(xml_file):
    """
    Get all band(s) name and order from a XML file.
    :param xml_file: str
        Path to the xml
    :return: list
        List (in order) of all bands in the XML.
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()
    l_band_order = []
    err_msg = None
    for t in root:
        if t.tag == 'IMD':
            l_band_order = [j.tag for j in t if str(j.tag).startswith('BAND_')]
        else:
            continue
    # if not l_band_order:
    #     err_msg = f"Could not locate band(s) name and order in provided xml file: {xml_file}"

    return l_band_order


def process_string(l: List[str]):
    p_band_order = []
    for s in l:
        s = s.split('_')[1]
        p_band_order.append(s)
    return p_band_order


def main(glob_params, list_params):
    images_list = tile_list_glob(**glob_params)
    source_pan = get_key_def('pan', list_params['source'], default=False, expected_type=bool)
    source_mul = get_key_def('mul', list_params['source'], default=False, expected_type=bool)
    prep_band = get_key_def('band', list_params['prep'], default=[], expected_type=list)
    out_pth = get_key_def('output_file', list_params, default='data_file.json', expected_type=str)

    for img in tqdm(images_list, desc="crawling images"):
        # print(img)
        data_struct = {'sensorID': '',
                       'pan_img': [],
                       'mul_img': [],
                       'mul_band': '',
                       'R_band': '',
                       'G_band': '',
                       'B_band': '',
                       'N_band': '',
                       'gpkg': {}}
        data_struct['sensorID'] = img.im_name
        if source_pan:
            if img.pan_tile_list is not None:
                for pan_img in img.pan_tile_list:
                    data_struct['pan_img'].append(str(pan_img))

        if source_mul:
            if img.mul_tile_list and img.mul_xml is not None:
                mul_xml = img.parent_folder / img.image_folder / img.mul_xml
                bands = process_string(get_band_order(mul_xml))
                data_struct['mul_band'] = bands
                for mul_img in img.mul_tile_list:
                    data_struct['mul_img'].append(str(mul_img))

        if prep_band:
            if set(prep_band).issubset({'R', 'G', 'B', 'N'}):
                for i_b in prep_band:
                    path = list((img.parent_folder / img.image_folder / img.prep_folder).glob(f'*_BAND_{i_b}.tif'))
                    if path:
                        data_struct[f'{i_b}_band'] = str(path[0])
                    else:
                        logging.warn(f'There are no compatible {i_b} band uint8 image found in {img.prep_folder}')
            else:
                logging.warn(f'There are no compatible image bands defined')

        gpkg_pth = img.parent_folder / img.im_name / img.image_folder.parent.name / 'geopakage' / '*/*.gpkg'
        gpkg_glob = glob.glob(f'{gpkg_pth}')

        if len(gpkg_glob) > 0:
            data_struct['gpkg'] = {Path(gpkg_glob[0]).parent.stem: gpkg_glob[0]}

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