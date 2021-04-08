from pathlib import Path

import logging

import rasterio
from rasterio.merge import merge
import re
from osgeo import gdal
from preprocess_glob import TileInfo, ImageInfo
from utils import validate_file_exists
import xml.etree.ElementTree as ET
import subprocess

logging.getLogger(__name__)


def pansharpen(img_info: ImageInfo,
               method: str = 'otb-bayes',
               ram: int = 4096,
               dry_run: bool = False,
               overwrite: bool = False):
    """
    Pansharpens self's multispectral and panchromatic rasters
    :param img_info: ImageInfo
        Image
    :param method: str
        Pansharpening method
    :param ram: int
        Max ram allocated to orfeo toolbox (if used) during pansharp. Default: 4 Gb
    :param dry_run: bool
        If True, skip time-consuming step, i.e. pansharp.
    :param overwrite: Bool
        Overwrite output if already exist.
    :return: Path
        Pansharpened raster file name
    """
    errors = []
    multispectral = img_info.parent_folder / img_info.image_folder / img_info.mul_merge
    panchromatic = img_info.parent_folder / img_info.image_folder / img_info.pan_merge

    # Determine output name (pansharp)
    pan_raster_splits = str(img_info.pan_merge.stem).split(img_info.mul_pan_info[1][1])
    pansharp_method = method.split("otb-")[-1] if method.startswith("otb-") else method
    output_psh_name = (pan_raster_splits[0] + ('-PSH-%s-' % pansharp_method) +
                       pan_raster_splits[-1] + "_" + img_info.dtype + ".TIF")
    output_psh_path = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / output_psh_name

    if not (multispectral.is_file() or panchromatic.is_file()):
        missing_mul_pan = f"Unable to pansharp due to missing mul {multispectral} or pan {panchromatic}"
        logging.warning(missing_mul_pan)
        errors.append(missing_mul_pan)
        return
    if output_psh_path.is_file() and not overwrite:
        pan_exist = f"Pansharp already exists: {output_psh_path}"
        logging.warning(pan_exist)
        return output_psh_path, errors
    # Choose between otb or numpy methods.
    if method.startswith("otb-"):
        method = method.split("otb-")[-1]
        from otb_apps import otb_pansharp
        try:
            if not dry_run:
                otb_pansharp(inp=str(panchromatic),
                             inxs=str(multispectral),
                             method=method,
                             ram=ram,
                             out=str(output_psh_path),
                             out_dtype=img_info.dtype)
        except RuntimeError as e:
            logging.warning(e)
            errors.append(e)
            return
    elif method in ["simple_brovey", "brovey", "simple_mean", "esri", "hsv"]:
        try:
            from pansharp_numpy import pansharpen
        except ImportError as e:
            logging.warning(e)
            errors.append(e)
            return
        if not dry_run:
            pansharpen(str(multispectral), (str(panchromatic)), method=method)
    elif method.startswith("gdal-"):
        gdal_pansharp(mul=str(multispectral), pan=str(panchromatic), out=str(output_psh_path), method=method)
    else:
        not_impl = f"Requested pansharp method {method} is not implemented"
        logging.warning(not_impl)
        errors.append(not_impl)

    if not output_psh_path.is_file():  # PansharpRaster object's attributes are defined as outputs are validated.
        psh_fail = f"Failed to created pansharp: {str(output_psh_path)}"
        logging.warning(psh_fail)
        errors.append(psh_fail)
    return output_psh_path, str(errors)


def gdal_pansharp(mul, pan, out, method="gdal-cubic"):

    method = method.replace('gdal-', '')
    command = f"gdal_pansharpen.py " \
              f"-of GTiff " \
              f"-r {str(method)} " \
              f"\"{str(pan)}\" \"{mul}\" " \
              f"\"{str(out)}\""

    subproc = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if subproc.stderr:
        logging.warning(subproc.stderr)
        logging.warning(f"could not pansharp with the following command: {command} ")


def gdal_8bit_rescale(infile, outfile, overwrite=False):
    """
    Rescale to 8 bit the input image. Uses gdal_translate.
    :param tile_info: TileInfo
        Image to scale
    :param overwrite: Bool
        Overwrite if output file already exist
    :return: Path
        Scaled raster file name
    """
    error = None

    if validate_file_exists(outfile) and not overwrite:
        logging.warning(f"8Bit file already exists: {outfile.name}. Will not overwrite")
        return error

    else:
        options_list = ['-ot Byte', '-of GTiff', '-scale']
        options_string = " ".join(options_list)

        gdal.Translate(str(outfile), str(infile), options=options_string)

        if not validate_file_exists(outfile):
            error = f"ERROR: Could not scale {str(outfile)}"
            logging.error(error)

    return error


def rasterio_merge_tiles(tile_list, outfile,
                         overwrite: bool = False):
    """
    Merge in a single tif file, multiples tifs from a list.
    :param image_info: ImageInfo
        Image
    :param overwrite: bool
    :return: Path
        Merged raster file name
    """
    error = None

    if validate_file_exists(outfile) and not overwrite:
        logging.warning(f"Merge file already exists: {outfile.name}. Will not overwrite")
        return Path(outfile), error

    try:
        # Open all tiles.
        sources = [rasterio.open(raster) for raster in tile_list]
    except rasterio.errors.RasterioIOError as err:
        logging.error(err)
        return Path(outfile), err

    # Merge
    mosaic, out_trans = merge(sources)
    # Copy the metadata
    out_meta = sources[0].meta.copy()

    # Update the metadata
    out_meta.update({"driver": "GTiff",
                     "height": mosaic.shape[1],
                     "width": mosaic.shape[2],
                     "transform": out_trans})
    # Write merged image
    with rasterio.open(outfile, "w", **out_meta) as dest:
        dest.write(mosaic)
    if not validate_file_exists(outfile):
        error = f"Could not merge image {outfile.stem}"
        logging.error(error)

    return Path(outfile), error


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
    if not l_band_order:
        err_msg = f"Could not locate band(s) name and order in provided xml file: {xml_file}"

    return l_band_order, err_msg


def gdal_split_band(img_file, xml_file,
                    overwrite: bool = False):
    """
    Split multi band file into single band files.
    :param image: ImageInfo
        Image
    :param overwrite: bool
        Overwrite files if they already exists.
    :return: List of written files.
    """
    list_band_order, err = get_band_order(str(xml_file))
    error = []
    list_band_file = []
    if err is None:
        for elem in list_band_order:

            out_filename = Path(f"{img_file.stem}_{elem}.tif")
            out_filepath = img_file.parent / out_filename

            if validate_file_exists(out_filepath) and not overwrite:
                logging.warning(f"{elem} file already exists: {out_filepath.name}. Will not overwrite")
                continue

            else:
                band_num = list_band_order.index(elem) + 1
                band_option = f"-b {band_num}"
                options_list = ['-of GTiff', band_option]
                options_string = " ".join(options_list)
                gdal.Translate(str(out_filepath), str(img_file), options=options_string)

                if not validate_file_exists(out_filepath):
                    err = f"Could not write singleband image {str(out_filepath)}"
                    error.append(err)
                    logging.error(err)
            list_band_file.append(out_filepath)
    else:
        error.append(err)
        logging.error(err)
    return list_band_file, error
