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
    errors: list = None


@dataclass
class ImageInfo:
    parent_folder: Path
    image_folder: Path
    prep_folder: Path = None
    tile_list: list = None
    merge_img_fp: Path = None
    band_file_list: list = None
    mul_xml: Path = None
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
        mul_rasters_glob = base_dir_res.glob(mul_glob_pattern)

        # Loop through glob generator object and retrieve individual multispectral images
        for mul_raster in tqdm(mul_rasters_glob, desc='Iterating through multispectral images'):  # mul_raster being a Path object
            mul_raster_rel = Path(mul_raster).relative_to(base_dir_res)  # Use only relative paths from here

            image_folder = mul_raster_rel.parents[1]
            mul_raster_rel = Path(mul_raster).relative_to(base_dir_res / image_folder)

            err_mgs = []
            length_err = "Check absolute path length. May exceed 260 characters."
            if not validate_file_exists(image_folder / mul_raster_rel):
                err_mgs.append(length_err)

            # 2. Find panchromatic image with relative glob pattern from multispectral pattern
            ################################################################################
            pan_glob_pattern = mul_pan_info[0][1] + "/*." + ext
            # assume panchromatic file has same extension as multispectral
            pan_rasters_glob = sorted((image_folder / mul_raster_rel.parent).glob(pan_glob_pattern))
            if len(pan_rasters_glob) == 0:
                missing_pan = f"The provided glob pattern {pan_glob_pattern} could not locate a potential" \
                              f"panchromatic raster to match {mul_raster_rel}." \
                              f"Skipping to next multispectral raster..."
                logging.warning(missing_pan)
                err_mgs.append(missing_pan)
                continue
            # Replace string that identifies the raster as a multispectral for one identifying panchromatic raster
            pan_best_guess = str(mul_raster_rel.name).replace(mul_pan_info[1][0], mul_pan_info[1][1])
            # Guess the panchromatic image's path using directory from glob results above. This file may not exist.
            pan_best_guess_rel_path = (pan_rasters_glob[0].parent.resolve() / pan_best_guess).relative_to(base_dir_res / image_folder)
            # Make a list of strings from paths given by glob results above.
            pan_rasters_str = []
            for potential_pan in pan_rasters_glob:
                # Resolve paths to avoid path length problems in Windows,
                # i.e. discard all relative references (ex.: "mul_dir/../pan_dir") making path longer
                pot_pan_dir = potential_pan.parent.resolve()
                pot_pan_rel = pot_pan_dir.joinpath(potential_pan.name).relative_to(base_dir_res / image_folder)
                pan_rasters_str.append(str(pot_pan_rel))
            # Get closest match between guessed name for panchromatic image and glob file names
            pan_raster_rel = Path(get_close_matches(str(pan_best_guess_rel_path), pan_rasters_str)[0])
            if not validate_file_exists(image_folder / pan_raster_rel):
                no_panchro_err = f"Panchromatic raster not found to match multispectral raster {mul_raster_rel}"
                logging.warning(no_panchro_err)
                err_mgs.append(no_panchro_err)
                continue

            # 3. Define parameters for future pansharp (and more), now that we've found mul/pan pair.
            ################################################################################
            try:
                raster = rasterio_raster_reader(str(image_folder / mul_raster_rel))  # Set output dtype as original multispectral dtype
            except rasterio.errors.RasterioIOError as e:
                logging.warning(e)
                continue
            dtype = raster.meta["dtype"]

            logging.debug(f"\nMultispectral image: {mul_raster_rel}\n"
                          f"Panchromatic image found: {pan_raster_rel}\n"
                          f"Multispectral datatype: {dtype}\n")

            # # Determine output path
            common_prefix = Path(os.path.commonprefix([str(mul_raster_rel.parent.resolve()),
                                                       str(pan_raster_rel.parent.resolve())]))
            # common_prefix = Path(common_prefix).relative_to(Path(base_dir_res).resolve())
            output_path = common_prefix.joinpath('PREP') if common_prefix.is_dir() else Path(str(common_prefix) + 'PREP')
            output_prep_path = Path(base_dir) / image_folder / output_path
            output_prep_path.parent.mkdir(exist_ok=True)

            process_steps = ['psh']
            if dtype != 'uint8':
                process_steps.append('scale')

            p = re.compile('_R\wC\w')
            mul_xml_name = Path(p.sub('', str(mul_raster_rel.stem)) + '.XML')
            mul_xml = Path(base_dir) / image_folder / mul_raster_rel.parent / mul_xml_name
            if not validate_file_exists(mul_xml):
                no_xml_err = f"No XML file found in {mul_xml}"
                logging.warning(no_xml_err)
                err_mgs.append(no_xml_err)
                continue

            # create new row and append to existing records in glob_output_list.
            tile_info = TileInfo(parent_folder=Path(base_dir), image_folder=image_folder, mul_pan_patern=mul_pan_info,
                                 mul_tile=mul_raster_rel, pan_tile=pan_raster_rel, prep_folder=output_path, dtype=dtype, process_steps=process_steps,
                                 mul_xml=mul_xml)
            # row = [str(base_dir), str(mul_raster_rel), str(pan_raster_rel), dtype, str(output_psh_rel), pansharp_method,
            #        str(output_cog_rel), err_mgs]
            # glob_output_list.append(tuple(row))
            glob_output_list.append(tile_info)
            out_csv.write_row(tile_info)

    mul_pan_pairs_ct = len(glob_output_list)
    logging.info(f"Found {mul_pan_pairs_ct} pair(s) of multispectral and panchromatic rasters with provided parameters")

    # 4. Find already pansharped images with a certain name pattern
    ################################################################################
    if psh_glob:  # if config file contains any search pattern, glob.
        for psh_glob_item, ext in product(psh_glob, extensions):
            psh_glob_pattern = psh_glob_item + "." + ext
            psh_rasters_glob = base_dir_res.glob(psh_glob_pattern)
            for psh_raster in tqdm(psh_rasters_glob, desc="Iterating through already pansharped images"):
                try:
                    raster = rasterio_raster_reader(str(psh_raster))  # Set output dtype as original multispectral dtype
                except rasterio.errors.RasterioIOError as e:
                    logging.warning(e)
                    continue
                psh_dtype = raster.meta["dtype"]

                psh_raster_rel = Path(psh_raster).relative_to(base_dir_res)  # Use only relative paths
                image_folder = psh_raster_rel.parents[1]
                psh_raster_rel = Path(psh_raster).relative_to(base_dir_res / image_folder)

                # # Determine output path

                output_path = Path('_'.join(str(psh_raster_rel.parent).split('_')[:-1]) + '_PREP')

                output_prep_path = Path(base_dir) / image_folder / output_path
                output_prep_path.mkdir(exist_ok=True)

                # output_cog_rel = psh_raster_rel.parent / (psh_raster_rel.stem + "-" + psh_dtype + "-cog" + psh_raster_rel.suffix)
                logging.debug(f"\nPansharp image found: {psh_raster_rel}\n")

                p = re.compile('_R\wC\w')
                mul_xml_name = Path(p.sub('', str(psh_raster_rel.stem)) + '.XML')
                mul_xml = Path(base_dir) / image_folder / psh_raster_rel.parent / mul_xml_name
                if not validate_file_exists(mul_xml):
                    no_xml_err = f"No XML file found in {mul_xml}"
                    logging.warning(no_xml_err)
                    continue

                process_steps = []
                if psh_dtype != 'uint8':
                    process_steps.append('scale')
                tile_info = TileInfo(parent_folder=Path(base_dir), image_folder=image_folder, psh_tile=psh_raster_rel, prep_folder=output_path,
                                     dtype=psh_dtype, process_steps=process_steps, last_processed_fp=Path(base_dir) / image_folder / psh_raster_rel,
                                     mul_xml=mul_xml)

                # row = [str(base_dir), "", "", psh_dtype, str(psh_raster_rel), "", str(output_cog_rel), ""]
                # glob_output_list.append(tuple(row))
                glob_output_list.append(tile_info)

    psh_ct = len(glob_output_list) - mul_pan_pairs_ct
    logging.info(f'Found {psh_ct} pansharped raster(s) with provided parameters')

    # Once all images were found and appended, sort, then save to csv if desired.
    # glob_output_list = sorted(glob_output_list, key=lambda x: x[4])
    # for row in glob_output_list:
    #     CsvLog.write_row(row=row)

    return glob_output_list


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preprocess execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    tile_list_glob(**params['glob'], pansharp_method=params['process']['method'])

    logging.info("Finished")
