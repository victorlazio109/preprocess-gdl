import argparse
import os
from itertools import product
from pathlib import Path
from difflib import get_close_matches
from typing import List
import logging
from dataclasses import dataclass
import re
import csv
import xml.etree.ElementTree as ET
import rasterio
from tqdm import tqdm

from utils import read_parameters, rasterio_raster_reader, validate_file_exists, CsvLogger

logging.getLogger(__name__)


@dataclass
class TileInfo:
    parent_folder: Path
    process_steps: list
    dtype: str
    image_folder: Path
    mul_pan_patern: list = None
    mul_tile: Path = None
    pan_tile: Path = None
    psh_tile: Path = None
    prep_folder: Path = None
    last_processed_fp: Path = None
    mul_xml: Path = None
    errors: str = None


@dataclass
class ImageInfo:
    parent_folder: Path
    image_folder: Path
    prep_folder: Path = None

    mul_tile_list: list = None
    pan_tile_list: list = None
    psh_tile_list: list = None

    mul_merge: Path = None
    pan_merge: Path = None
    psh_merge: Path = None

    band_file_list: list = None

    mul_xml: Path = None
    pan_xml: Path = None
    psh_xml: Path = None
    process_steps: list = None
    mul_pan_info: list = None
    dtype: str = None

    errors: str = None


def list_of_tiles_from_csv(path, delimiter=";"):
    """
    Create list of tuples from a csv file
    :param path: Path or str
        path to csv file
    :param delimiter: str
        type of delimiter for inputted csv
    :return:
    """
    assert Path(path).suffix == '.csv', ('Not a ".csv.": ' + path)
    with open(str(path), newline='') as f:
        reader = csv.reader(f, delimiter=delimiter)
        # data = [tuple(row) for row in reader]
        data = []
        for row in reader:
            mul_tile = Path(row[5]) if row != 'None' else None
            pan_tile = Path(row[6]) if row != 'None' else None
            psh_tile = Path(row[7]) if row != 'None' else None
            last_processed_fp = Path(row[9]) if row != 'None' else None
            process_steps = row[1].split(",")
            mul_pan_patern = row[4].split(",")

            tile = TileInfo(parent_folder=Path(row[0]), process_steps=process_steps, dtype=row[2], image_folder=Path(row[3]),
                            mul_pan_patern=mul_pan_patern, mul_tile=mul_tile, pan_tile=pan_tile, psh_tile=psh_tile,
                            prep_folder=Path(row[8]), last_processed_fp=last_processed_fp)
            data.append(tile)
    return data


def get_tiles_from_xml(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()
    filename_lst = []
    for t in root.findall('./TIL/TILE/FILENAME'):
        filename_lst.append(t.text)

    return filename_lst


def tile_list_glob(base_dir: str,
                  mul_pan_glob: List[str] = [],
                  mul_pan_str: List[str] = [],
                  psh_glob: List[str] = [],
                  extensions: List[str] = [],
                  out_csv: str = ""):
    """
    Glob through specified directories for (1) pairs of multispectral and panchromatic rasters or (2) pansharp rasters.
    Save as csv and/or return as list.
    :param base_dir: str
        Base directory where globbing will occur.
    :param mul_pan_glob: list of str
        List of list of patterns linking multispectral and panchrom. rasters. Patterns are a two-item list:
        (1) glob pattern to reach multispectral raster (excluding extension);
        (2) pattern to panchrom. raster from multispectral raster,
        e.g.: ["**/*_MUL/*-M*_P00?", "../*_PAN"].
    :param mul_pan_str: list of str
        List of list of string sections that identify multispectral and panchrom. rasters inside filename,
        e.g. [['-M', '-P'],["_MSI", "_PAN"]].
    :param psh_glob: list of str
        List of glob patterns to find panchromatic rasters.
    :param extensions: list of str
        List of extensions (suffixes) the raster files may bear, e.g. ["tif", "ntf"].
    :param out_csv: str
        Output csv where info about processed files and log messages will be saved.
    :return:
        list of lists (rows) containing info about files found, output pansharp name (if applies) and more.
    """
    assert len(mul_pan_glob) == len(mul_pan_str), "Missing info about multispectral and panchromatic images"

    # Reorganize mul/pan glob and str info as list of lists each containing a tuple.
    # e.g. [('Sherbrooke/**/*_MUL/*-M*_P00?', '../*_PAN'), ('-M', '-P')]. See pansharp_glob()'s docstring for more info.
    mul_pan_info_list = [[tuple(mul_pan_glob[x]), tuple(mul_pan_str[x])] for x in mul_pan_glob]

    os.chdir(base_dir)  # Work in base directory

    # TODO: test execution of preprocess_glob.py
    import logging.config
    out_log_path = Path("./logs")
    out_log_path.mkdir(exist_ok=True)
    logging.basicConfig(filename='logs/prep_glob.log', level=logging.DEBUG)
    logging.info("Started")

    base_dir_res = Path(base_dir).resolve()  # Resolved path is useful in section 2 (search for panchromatic).

    if out_csv != "":
        out_csv = CsvLogger(out_csv=out_csv, info_type='tile')

    glob_output_list = []

    # 1. GLOB to all multispectral images in base directory using inputted pattern. Create generator from glob search.
    ################################################################################
    for mul_pan_info, ext in product(mul_pan_info_list, extensions):  # FIXME: if list is empty, Nonetype will cause TypeError
        mul_glob_pattern = mul_pan_info[0][0] + "." + ext
        # FIXME: there may be compatibilty issues with glob's case sensitivity in Linux. Working ok on Windows.
        # More info: https://jdhao.github.io/2019/06/24/python_glob_case_sensitivity/
        mul_glob = base_dir_res.glob(mul_glob_pattern)

        # Loop through glob generator object and retrieve xml in multispectral folder
        for mul_xml in tqdm(mul_glob, desc='Iterating through multispectral xml'):  # mul_raster being a Path object
            mul_rel = Path(mul_xml).relative_to(base_dir_res)  # Use only relative paths from here

            image_folder = mul_rel.parents[1]
            mul_rel = Path(mul_xml).relative_to(base_dir_res / image_folder)

            err_mgs = []
            length_err = "Check absolute path length. May exceed 260 characters."
            if not validate_file_exists(image_folder / mul_rel):
                err_mgs.append(length_err)

            # get tile list from xml
            lst_mul_tiles = get_tiles_from_xml(mul_xml)

            # 2. Find panchromatic image with relative glob pattern from multispectral pattern
            ################################################################################
            pan_glob_pattern = mul_pan_info[0][1] + "/*." + ext
            # assume panchromatic file has same extension as multispectral
            pan_glob = sorted((image_folder / mul_rel.parent).glob(pan_glob_pattern))
            if len(pan_glob) == 0:
                missing_pan = f"The provided glob pattern {pan_glob_pattern} could not locate a potential" \
                              f"panchromatic raster to match {mul_rel}."
                logging.warning(missing_pan)
                err_mgs.append(missing_pan)
                continue
            # Replace string that identifies the raster as a multispectral for one identifying panchromatic raster
            pan_best_guess = str(mul_rel.name).replace(mul_pan_info[1][0], mul_pan_info[1][1])
            # Guess the panchromatic image's path using directory from glob results above. This file may not exist.
            pan_best_guess_rel_path = (pan_glob[0].parent.resolve() / pan_best_guess).relative_to(base_dir_res / image_folder)
            # Make a list of strings from paths given by glob results above.
            pan_str = []
            for potential_pan in pan_glob:
                # Resolve paths to avoid path length problems in Windows,
                # i.e. discard all relative references (ex.: "mul_dir/../pan_dir") making path longer
                pot_pan_dir = potential_pan.parent.resolve()
                pot_pan_rel = pot_pan_dir.joinpath(potential_pan.name).relative_to(base_dir_res / image_folder)
                pan_str.append(str(pot_pan_rel))
            # Get closest match between guessed name for panchromatic image and glob file names
            pan_rel = Path(get_close_matches(str(pan_best_guess_rel_path), pan_str)[0])
            if validate_file_exists(image_folder / pan_rel):
                lst_pan_tiles = get_tiles_from_xml(image_folder / pan_rel)
            else:
                no_panchro_err = f"Panchromatic xml not found to match multispectral xml {mul_rel}"
                logging.warning(no_panchro_err)
                err_mgs.append(no_panchro_err)
                continue

            # Check both mul and pan lists are the same length.
            if len(lst_mul_tiles) != len(lst_pan_tiles):
                xml_err = f"The number of tiles in multispectral and panchromatic xmls do not match for image {image_folder}."
                logging.warning(xml_err)
                err_mgs.append(xml_err)
                continue

            process_steps = ['psh']
            if len(lst_mul_tiles) > 1:
                process_steps.append('merge')
            elif len(lst_mul_tiles) == 0:
                xml_err = f"Could not find any tile in xmls for image {image_folder}."
                logging.warning(xml_err)

            try:
                with rasterio_raster_reader(str(mul_xml.parent / Path(lst_mul_tiles[0]))) as src:  # Set output dtype as original multispectral dtype
                    dtype = src.meta["dtype"]
            except rasterio.errors.RasterioIOError as e:
                logging.warning(e)
                continue

            logging.debug(f"\nMultispectral: {mul_rel}\n"
                          f"Panchromatic: {pan_rel}\n"
                          f"Multispectral datatype: {dtype}\n")

            # # Determine output path
            p = re.compile('_M\w\w')
            output_path = Path(p.sub('_PREP', str(mul_rel.parent)))
            output_prep_path = Path(base_dir) / image_folder / output_path
            output_prep_path.mkdir(exist_ok=True)
            if not output_prep_path.is_dir():
                raise ValueError(f"Could not create folder {output_prep_path}")

            if dtype != 'uint8':
                process_steps.append('scale')

            mul_tile_list = [Path(base_dir) / image_folder / mul_rel.parent / Path(elem) for elem in lst_mul_tiles]
            pan_tile_list = [Path(base_dir) / image_folder / pan_rel.parent / Path(elem) for elem in lst_pan_tiles]

            # create new row and append to existing records in glob_output_list.
            img_info = ImageInfo(parent_folder=Path(base_dir), image_folder=image_folder, prep_folder=output_path, mul_tile_list=mul_tile_list,
                                 pan_tile_list=pan_tile_list, mul_xml=mul_rel, pan_xml=pan_rel, mul_pan_info=mul_pan_info,
                                 process_steps=process_steps, dtype=dtype)

            glob_output_list.append(img_info)
            # out_csv.write_row(img_info)

    mul_pan_pairs_ct = len(glob_output_list)
    logging.info(f"Found {mul_pan_pairs_ct} pair(s) of multispectral and panchromatic rasters with provided parameters")

    # 4. Find already pansharped images with a certain name pattern
    ################################################################################
    if psh_glob:  # if config file contains any search pattern, glob.
        for psh_glob_item, ext in product(psh_glob, extensions):
            psh_glob_pattern = psh_glob_item + "." + ext
            psh_xml_glob = base_dir_res.glob(psh_glob_pattern)
            for psh_xml in tqdm(psh_xml_glob, desc="Iterating through already pansharped images"):

                psh_rel = Path(psh_xml).relative_to(base_dir_res)  # Use only relative paths
                image_folder = psh_rel.parents[1]
                psh_rel = Path(psh_xml).relative_to(base_dir_res / image_folder)

                if validate_file_exists(psh_xml):
                    lst_psh_tiles = get_tiles_from_xml(psh_xml)
                else:
                    no_xml_err = f"No XML file found in {psh_xml}"
                    logging.warning(no_xml_err)
                    continue

                process_steps = []
                if len(lst_psh_tiles) > 1:
                    process_steps.append('merge')
                elif len(lst_psh_tiles) == 0:
                    xml_err = f"Could not find any tile in xmls for image {image_folder}."
                    logging.warning(xml_err)

                try:
                    with rasterio_raster_reader(str(psh_xml.parent / Path(lst_psh_tiles[0]))) as src:
                        psh_dtype = src.meta["dtype"]
                except rasterio.errors.RasterioIOError as e:
                    logging.warning(e)
                    continue

                # Determine output path
                output_path = Path('_'.join(str(psh_rel.parent).split('_')[:-1]) + '_PREP')

                output_prep_path = Path(base_dir) / image_folder / output_path
                output_prep_path.mkdir(exist_ok=True)

                logging.debug(f"\nPansharp image found: {psh_rel}\n")

                if psh_dtype != 'uint8':
                    process_steps.append('scale')

                psh_tile_list = [Path(base_dir) / image_folder / psh_rel.parent / Path(elem) for elem in lst_psh_tiles]
                img_info = ImageInfo(parent_folder=Path(base_dir), image_folder=image_folder, prep_folder=output_path, psh_tile_list=psh_tile_list,
                                     dtype=psh_dtype, psh_xml=psh_xml, process_steps=process_steps, mul_pan_info=psh_glob_pattern)

                glob_output_list.append(img_info)
                # out_csv.write_row(img_info)

    psh_ct = len(glob_output_list) - mul_pan_pairs_ct
    logging.info(f'Found {psh_ct} pansharped raster(s) with provided parameters')

    return glob_output_list


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preprocess execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    tile_list_glob(**params['glob'])

    logging.info("Finished")
