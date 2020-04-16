import argparse
import os
from itertools import product
from pathlib import Path
from difflib import get_close_matches
from typing import List
import logging

from tqdm import tqdm

from utils import read_parameters, rasterio_raster_reader, validate_file_exists, CsvLogger

logging.getLogger(__name__)


def pansharp_glob(base_dir: str,
                  mul_pan_glob: List[str] = [],
                  mul_pan_str: List[str] = [],
                  psh_glob: List[str] = [],
                  extensions: List[str] = [],
                  pansharp_method: str = "",
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
    :param pansharp_method: str
        Method (algorithm) used to pansharp the mul/pan pair of rasters
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

    base_dir = Path(base_dir).resolve()  # Resolved path is useful in section 2 (search for panchromatic).
    pansharp_method = pansharp_method.split("otb-")[-1] if pansharp_method.startswith("otb-") else pansharp_method

    CsvLog = CsvLogger(out_csv=out_csv)

    glob_output_list = []

    # 1. GLOB to all multispectral images in base directory using inputted pattern. Create generator from glob search.
    ################################################################################
    for mul_pan_info, ext in product(mul_pan_info_list, extensions):  # FIXME: if list is empty, Nonetype will cause TypeError
        mul_glob_pattern = mul_pan_info[0][0] + "." + ext
        # FIXME: there may be compatibilty issues with glob's case sensitivity in Linux. Working ok on Windows.
        # More info: https://jdhao.github.io/2019/06/24/python_glob_case_sensitivity/
        mul_rasters_glob = base_dir.glob(mul_glob_pattern)

        # Loop through glob generator object and retrieve individual multispectral images
        for mul_raster in tqdm(mul_rasters_glob, desc='Iterating through multispectral images'):  # mul_raster being a Path object
            mul_raster_rel = Path(mul_raster).relative_to(base_dir)  # Use only relative paths from here
            err_mgs = []
            length_err = ("Check absolute path length. May exceed 260 characters.")
            if not validate_file_exists(mul_raster_rel):
                err_mgs.append(length_err)

            # 2. Find panchromatic image with relative glob pattern from multispectral pattern
            ################################################################################
            pan_glob_pattern = mul_pan_info[0][1] + "/*." + ext
            # assume panchromatic file has same extension as multispectral
            pan_rasters_glob = sorted(mul_raster_rel.parent.glob(pan_glob_pattern))
            if len(pan_rasters_glob) == 0:
                missing_pan = f'The provided glob pattern {pan_glob_pattern} could not locate a potential ' \
                              f'panchromatic raster to match {mul_raster_rel}. ' \
                              'Skipping to next multispectral raster...'
                logging.warning(missing_pan)
                err_mgs.append(missing_pan)
                continue
            # Replace string that identifies the raster as a multispectral for one identifying panchromatic raster
            pan_best_guess = str(mul_raster_rel.name).replace(mul_pan_info[1][0], mul_pan_info[1][1])
            # Guess the panchromatic image's path using directory from glob results above. This file may not exist.
            pan_best_guess_rel_path = (pan_rasters_glob[0].parent.resolve() / pan_best_guess).relative_to(base_dir)
            # Make a list of strings from paths given by glob results above.
            pan_rasters_str = []
            for potential_pan in pan_rasters_glob:
                # Resolve paths to avoid path length problems in Windows,
                # i.e. discard all relative references (ex.: "mul_dir/../pan_dir") making path longer
                pot_pan_dir = potential_pan.parent.resolve()
                pot_pan_rel = pot_pan_dir.joinpath(potential_pan.name).relative_to(base_dir)
                pan_rasters_str.append(str(pot_pan_rel))
            # Get closest match between guessed name for panchromatic image and glob file names
            pan_raster_rel = Path(get_close_matches(str(pan_best_guess_rel_path), pan_rasters_str)[0])
            if not validate_file_exists(pan_raster_rel):
                no_panchro_err = f"Panchromatic raster not found to match multispectral raster {mul_raster_rel}"
                logging.warning(no_panchro_err)
                err_mgs.append(no_panchro_err)
                continue


            # 3. Define parameters for future pansharp (and more), now that we've found mul/pan pair.
            ################################################################################
            raster = rasterio_raster_reader(str(mul_raster_rel))  # Set output dtype as original multispectral dtype
            dtype = raster.meta["dtype"]

            logging.debug(f"\nMultispectral image: {mul_raster_rel}\n"
                          f"Panchromatic image found: {pan_raster_rel}\n"
                          f"Multispectral datatype: {dtype}\n")

            # Determine output path
            common_prefix = Path(os.path.commonprefix([str(mul_raster_rel.parent.resolve()),
                                                       str(pan_raster_rel.parent.resolve())]))
            common_prefix = Path(common_prefix).relative_to(Path(base_dir).resolve())
            output_path = common_prefix.joinpath('PREP') if common_prefix.is_dir() \
                else Path(str(common_prefix)+'PREP')

            # Determine output name (pansharp and cog)
            pan_raster_splits = str(pan_raster_rel.stem).split(mul_pan_info[1][1])
            output_psh_name = (pan_raster_splits[0] + ('-PSH-%s-' % (pansharp_method)) +
                               pan_raster_splits[-1] + "_" + dtype + ".TIF")
            output_psh_rel = output_path / output_psh_name
            if len(str(output_psh_rel.absolute())) >= 260:
                err_mgs.append(length_err)

            output_cog_name = output_psh_name.replace("-PSH-{}-".format(pansharp_method),
                                                      "-PSH-{}-cog-".format(pansharp_method))
            output_cog_rel = output_path / output_cog_name
            if len(str(output_cog_rel.absolute())) >= 260:
                err_mgs.append(length_err)

            # create new row and append to existing records in glob_output_list.
            row = [str(base_dir), str(mul_raster_rel), str(pan_raster_rel), dtype, str(output_psh_rel), pansharp_method,
                   str(output_cog_rel), err_mgs]
            glob_output_list.append(tuple(row))

    # 4. Find already pansharped images with a certain name pattern
    ################################################################################
    if psh_glob:  # if config file contains any search pattern, glob.
        for psh_glob_item, ext in product(psh_glob, extensions):
            psh_glob_pattern = psh_glob_item + "." + ext
            psh_rasters_glob = base_dir.glob(psh_glob_pattern)
            for psh_raster in tqdm(psh_rasters_glob, desc="Iterating through already pansharped images"):
                raster = rasterio_raster_reader(str(psh_raster))  # Set output dtype as original multispectral dtype
                psh_dtype = raster.meta["dtype"]
                psh_raster_rel = Path(psh_raster).relative_to(base_dir)  # Use only relative paths
                output_cog_rel = psh_raster_rel.parent / (psh_raster_rel.stem + "-" + psh_dtype + "-cog" + psh_raster_rel.suffix)
                logging.debug(f"\nPansharp image found: {psh_raster_rel}\n")

                row = [str(base_dir), "", "", psh_dtype, str(psh_raster_rel), "", output_cog_rel, ""]
                glob_output_list.append(tuple(row))

    # Once all images were found and appended, sort, then save to csv if desired.
    glob_output_list = sorted(glob_output_list, key=lambda x: x[4])
    for row in glob_output_list:
        CsvLog.write_row(row=row)

    logging.info('Found %d pair(s) of multispectral and panchromatic rasters with provided parameters' % len(glob_output_list))
    return glob_output_list


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preprocess execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    pansharp_glob(**params['glob'], pansharp_method=params['pansharp']['method'])

    logging.info("Finished")