import glob
import re
import json
import argparse
import logging
import psutil
import rasterio
import numpy as np
from rasterio.windows import Window
from rasterio.plot import reshape_as_image
from tqdm import tqdm
from pathlib import Path
from functools import reduce
from preprocess_glob import tile_list_glob
from typing import List
from utils import read_parameters, get_key_def

logging.getLogger(__name__)
logging.basicConfig(filename='logs/prep_glob.log', level=logging.DEBUG)
all_dict = {'all_images': []}
pattern = "([a-zA-Z]+)([0-9]+)"


def calc_ram_mem():
    return psutil.virtual_memory().available


def reorder_bands(a: List[str], b: List[str]):
    read_band_order = []
    for band in a:
        if band in b:
            read_band_order.insert(a.index(band) + 1, b.index(band) + 1)
            # print(f'{a.index(band)},{band}, {b.index(band)}')

    return read_band_order


def raster_reader(rst_pth, tile_size, dist_samples, *band_order):
    with rasterio.open(rst_pth) as src:
        # print(calc_ram_mem())
        # print('pan_shape', src.shape)
        # src_size = reduce(lambda x, y: x*y, src.shape)
        # print('pan_size', src_size)
        # dummy = np.empty((src.height, src.width), dtype=np.uint8)
        for row in range(0, src.height, dist_samples):
            for column in range(0, src.width, dist_samples):
                # dum = (dummy[row:row + sample_size, column:column + sample_size])
                window = Window.from_slices(slice(row, row + tile_size),
                                            slice(column, column + tile_size))
                if band_order:
                    window_array = reshape_as_image(src.read(band_order[0], window=window))
                else:
                    window_array = reshape_as_image(src.read(window=window))
                # print('block_shape', window_array.shape)
                # print('dummy_shape', dum.shape)
                # if block_array.shape != dum.shape:
                #     print('Yikes')
                # else:
                #     print('Yaay!!')
    return window_array

sample_size = 1024
overlap = 25
dist_samples = round(sample_size * (1 - (overlap / 100)))
print(dist_samples)

def main(glob_params, list_params):
    # images_list = tile_list_glob(**glob_params)
    source_pan = get_key_def('pan', list_params['source'], default=False, expected_type=bool)
    source_mul = get_key_def('mul', list_params['source'], default=False, expected_type=bool)
    mul_band_order = get_key_def('mulband', list_params['source'], default=[], expected_type=list)
    prep_band = get_key_def('band', list_params['prep'], default=[], expected_type=list)
    # geopackage = glob.glob(get_key_def('gpkg', list_params, default='', expected_type=str))
    in_pth = get_key_def('input_file', list_params, default='data_file.json', expected_type=str)

    with open(Path(in_pth), 'r') as fin:
        dict_images = json.load(fin)

    for i_dict in dict_images['all_images']:

        if source_pan:
            if not len(i_dict['pan_img']) == 0:
                for img_pan in i_dict['pan_img']:
                    raster_reader(img_pan, sample_size, dist_samples)
        if source_mul:
            if not len(i_dict['mul_img']) == 0:
                band_order = reorder_bands(i_dict['mul_band'], mul_band_order)
                for img_mul in i_dict['mul_img']:
                    x = raster_reader(img_mul, sample_size, dist_samples, band_order)
                    # with rasterio.open(img_mul) as src:
                    #     np_array = src.read(band_order)
                    #     print(src.width)
                    #     print(type(band_order))
                    #     print(np_array.shape)

        # if prep_band:
        #     if set(prep_band).issubset({'R', 'G', 'B', 'N'}):
        #         bands = []
        #         for ib in prep_band:
        #             b_idx = raster_reader(i_dict[f'{ib}_band'], sample_size, dist_samples)
        #             for bi in range(len(prep_band)):
        #                 bands.append(b_idx)
        #         print(len(bands))






    # print(calc_ram_mem())

                        # for block_index, window in src.block_windows(1):
                        #     block_array = src.read(window=window)
                        #     print('block_shape', block_array.shape)


    # for img in tqdm(images_list, desc="crawling images"):
    #     data_struct = {'sensorID': '',
    #                    'pan_img': [],
    #                    'mul_img': [],
    #                    'R_band': '',
    #                    'G_band': '',
    #                    'B_band': '',
    #                    'N_band': '',
    #                    'gpkg': ''}
    #     data_struct['sensorID'] = img.im_name
    #     if geopackage:
    #         for gpkg in geopackage:
    #             A = re.split(pattern, Path(gpkg).stem.replace('_', ""))
    #             B = re.split(pattern, f'{img.image_folder.parent.name}'.replace("_", ""))[:len(A)]
    #             if set(A).issubset(set(B)):
    #                 data_struct['gpkg'] = gpkg
    #
    #     if source_pan:
    #         if img.pan_tile_list is not None:
    #             for pan_img in img.pan_tile_list:
    #                 data_struct['pan_img'].append(str(pan_img))
    #
    #     if source_mul:
    #         if img.mul_tile_list is not None:
    #             for mul_img in img.mul_tile_list:
    #                 data_struct['mul_img'].append(str(mul_img))
    #
    #     if prep_band:
    #         if set(prep_band).issubset({'R', 'G', 'B', 'N'}):
    #             for i_b in prep_band:
    #                 path = list((img.parent_folder / img.image_folder / img.prep_folder).glob(f'*uint8_BAND_{i_b}.tif'))
    #                 if path:
    #                     data_struct[f'{i_b}_band'] = str(path[0])
    #                 else:
    #                     logging.warn(f'There are no compatible {i_b} band uint8 image found in {img.prep_folder}')
    #         else:
    #             logging.warn(f'There are no compatible image bands defined')
    #
    #     all_dict['all_images'].append(data_struct)
    #
    # with open(out_pth, 'w') as fout:
    #     json.dump(all_dict, fout, indent=4)

    print('\n\nProcess Completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(config_path)

    # log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'], list_params=params['read_img'])