import os
from pathlib import Path
from typing import Union, List
import logging
import warnings

import rasterio
from rasterio.merge import merge
import re
import gdal
from preprocess_glob import TileInfo, ImageInfo
from utils import validate_file_exists

logging.getLogger(__name__)


def rio_cogeo_translate(in_raster: Union[Path, str],
                        out_raster: Union[Path, str],
                        ovr_blocksize: int = 128,
                        compress_mode: str = "deflate"):
    """
    Translate a raster to a Cloud-Optimized-Geotiff
    :param in_raster: Path or str
        Path to input raster
    :param out_raster: Path or str
        Path to output raster
    :param ovr_blocksize:
        Overview blocksize
    :param compress_mode:
        Compression mode ("deflate", "LZW", etc.)
    :return: Write COG to disk.
    """
    try:
        from rio_cogeo.profiles import cog_profiles
        from rio_cogeo.cogeo import cog_translate
    except ImportError as e:
        logging.warning(e)
        return

    config = dict(GDAL_NUM_THREADS="ALL_CPUS",
                  GDAL_TIFF_INTERNAL_MASK=False,
                  GDAL_TIFF_OVR_BLOCKSIZE=str(ovr_blocksize))
    dst_profile = cog_profiles.get(compress_mode)
    dst_profile.update(dict(BIGTIFF="YES"))
    cog_translate(in_raster, out_raster, dst_profile, config=config)


class PansharpRaster:
    all_objects = []

    def __init__(self,
                 basedir: Path,
                 multispectral: Path = None,
                 panchromatic: Path = None,
                 pansharp: Path = None,
                 cog: Path = None,
                 dtype: str = "",
                 method: str = "",
                 trim: Union[int, List] = 0,
                 copy_to_8bit: bool = True,
                 cog_delete_source: bool = False):
        self.basedir = basedir
        assert basedir.is_dir()

        if not validate_file_exists(multispectral):
            logging.warning(f"Could not locate multispectral image \"{multispectral}\"")
            self.multispectral = None
        else:
            self.multispectral = multispectral

        self.panchromatic = panchromatic
        if not validate_file_exists(self.panchromatic):
            logging.warning(f"Could not locate panchromatic image \"{self.panchromatic}\"")
            self.panchromatic = None

        self.pansharp = pansharp if validate_file_exists(pansharp) else None
        self.cog = cog if validate_file_exists(cog) else None

        self.dtype = dtype
        assert dtype in ["uint8", "int16", "uint16", "int32", "uint32"]

        self.method = method

        if isinstance(trim, int):
            self.trim_lower = self.trim_higher = trim
        elif isinstance(trim, list):
            assert len(trim) == 2, 'Two values should be given as trim values. {} values were given'.format(len(trim))
            self.trim_lower, self.trim_higher = trim

        self.copy_to_8bit = copy_to_8bit
        self.pansharp_8bit_copy = None
        self.pansharp_size = 0
        self.cog_8bit_copy = None
        self.cog_size = 0
        self.cog_delete_source = cog_delete_source
        self.errors = []

        PansharpRaster.all_objects.append(self)

    def rescale_trim(self,
                     out_file: Union[str, Path],
                     dry_run: bool = False):
        """
        Change the pixel type and rescale the image’s dynamic
        See: https://www.orfeo-toolbox.org/CookBook/Applications/app_DynamicConvert.html
        :param out_file: str
            Output 8bit pansharp path
        :param dry_run: bool
            If True, skip time-consuming step, i.e. rescale.
        :return: Rescaled 8bit pansharp on disk
        """
        from otb_apps import otb_8bit_rescale

        if validate_file_exists(self.pansharp):
            infile = self.pansharp
        elif validate_file_exists(self.cog):
            infile = self.cog
        else:
            logging.warning(f"Could not find input 16bit raster to rescale to {out_file}")
            return
        if not dry_run:
            otb_8bit_rescale(infile=str(infile),
                             outfile=out_file,
                             trim_lower=self.trim_lower,
                             trim_higher=self.trim_higher)
        if Path(out_file).is_file():
            self.pansharp_8bit_copy = Path(out_file)
        else:
            psh_fail_8bit = f"Failed to create 8bit pansharp: {out_file}"
            logging.warning(psh_fail_8bit)
            self.errors.append(psh_fail_8bit)

    def coggify(self,
                out_file: Union[str, Path],
                uint8_copy: bool = False,
                dry_run: bool = False,
                delete_source: bool = False,
                overwrite: bool = False):
        """
        Create and validate cog-geotiff of pansharp
        :param out_file: str
            Output cog geotiff
        :param uint8_copy: bool
            if True, cog will be create for 8bit copy of pansharp, if exists.
        :param inp_size_threshold: int
            If input pansharp is larger than this size (in Gb), processing will be skipped.
            Helps prevent Python from crashing.
        :param dry_run: bool
            If True, skip time-consuming step, i.e. cogging.
        :param delete_source: bool
            if True, source pansharp will be deleted after cog is created and validated.
        :param overwrite: bool
            if True, output file will be overwritten if it exists.
        :return: Cogged geotiff on disk
        """
        try:
            from rio_cogeo.cogeo import cog_validate
        except ImportError as e:
            logging.warning(e)
            return

        # Define input pansharp depending on uint8_copy parameter
        in_psh = self.pansharp_8bit_copy if uint8_copy else self.pansharp
        # If output not found, check if input exist before processing. If not found, return, else proceed to cogging.
        if not validate_file_exists(out_file) or overwrite:
            if not in_psh:
                miss_inp_cog = f"Input file {in_psh} not found. Skipping to next file ..."
                logging.warning(miss_inp_cog)
                self.errors.append(miss_inp_cog)
                return
            else:
                logging.info(f"COGging {out_file}")
                if not dry_run:
                    try:
                        rio_cogeo_translate(in_psh, out_file)
                    except rasterio.errors.CRSError:
                        invalid_crs = f"invalid CRS for {in_psh}"
                        logging.warning(invalid_crs)
                        self.errors.append(invalid_crs)
                    except Exception as e:
                        logging.warning(e)
                        self.errors.append(e)
        else:
            logging.info("COG file %s already exists...", out_file)

        # if cog is validated, set out_file as value to corresponding attribute.
        if validate_file_exists(out_file):
            if cog_validate(out_file):
                if not uint8_copy:
                    self.cog = out_file
                else:
                    self.cog_8bit_copy = out_file
                if delete_source and in_psh and not dry_run:
                    try:
                        os.remove(in_psh)
                    except PermissionError as e:
                        logging.warning(e)


def pansharpen(tile_info: TileInfo,
               method: str = 'otb-bayes',
               ram: int = 4096,
               dry_run: bool = False,
               overwrite: bool = False):
    """
    Pansharpens self's multispectral and panchromatic rasters
    :param output_psh: str
        Output pansharp path
    :param ram: int
        Max ram allocated to orfeo toolbox (if used) during pansharp. Default: 4 Gb
    :param dry_run: bool
        If True, skip time-consuming step, i.e. pansharp.
    :return: Pansharp raster on disk
    """
    errors = []
    multispectral = tile_info.parent_folder / tile_info.image_folder / tile_info.mul_tile
    panchromatic = tile_info.parent_folder / tile_info.image_folder / tile_info.pan_tile

    # Determine output name (pansharp)
    pan_raster_splits = str(tile_info.pan_tile.stem).split(tile_info.mul_pan_patern[1][1])
    pansharp_method = method.split("otb-")[-1] if method.startswith("otb-") else method
    output_psh_name = (pan_raster_splits[0] + ('-PSH-%s-' % pansharp_method) +
                       pan_raster_splits[-1] + "_" + tile_info.dtype + ".TIF")
    output_psh_path = tile_info.parent_folder / tile_info.image_folder / tile_info.prep_folder / output_psh_name

    if not (multispectral.is_file() or panchromatic.is_file()):
        missing_mul_pan = f"Unable to pansharp due to missing mul {multispectral} or pan {panchromatic}"
        logging.warning(missing_mul_pan)
        errors.append(missing_mul_pan)
        return
    if output_psh_path.is_file() and not overwrite:
        pan_exist = f"Pansharp already exists: {output_psh_path}"
        logging.warning(pan_exist)
        errors.append(pan_exist)
        return output_psh_path
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
                             out_dtype=tile_info.dtype)
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
    else:
        not_impl = f"Requested pansharp method {method} is not implemented"
        logging.warning(not_impl)
        errors.append(not_impl)

    if not output_psh_path.is_file():  # PansharpRaster object's attributes are defined as outputs are validated.
        psh_fail = f"Failed to created pansharp: {str(output_psh_path)}"
        logging.warning(psh_fail)
        errors.append(psh_fail)
    return output_psh_path


def gdal_8bit_rescale(tile_info: TileInfo, overwrite=False):

    infile = tile_info.last_processed_fp
    outfile_name = Path(str(infile.stem).replace(f"_{tile_info.dtype}", "_uint8.tif")) \
        if str(infile.stem).endswith(f"_{tile_info.dtype}") \
        else f"{str(infile.stem)}_uint8.tif"
    outfile = tile_info.parent_folder / tile_info.image_folder / tile_info.prep_folder / outfile_name

    if validate_file_exists(outfile) and not overwrite:
        pan_exist = f"8Bit file already exists: {outfile.name}. Will not overwrite"
        warnings.warn(pan_exist)
        return outfile

    else:
        options_list = ['-ot Byte', '-of GTiff', '-scale']
        options_string = " ".join(options_list)

        gdal.Translate(str(outfile), str(infile), options=options_string)

    return Path(outfile)


def rasterio_merge_tiles(image_info: ImageInfo):

    p = re.compile('R\wC\w')
    outfile_name = p.sub('Merge', str(image_info.tile_list[0].stem)) + ".tif"
    outfile = str(image_info.parent_folder / image_info.image_folder / image_info.prep_folder) / Path(outfile_name)

    sources = [rasterio.open(raster) for raster in image_info.tile_list]

    mosaic, out_trans = merge(sources)
    # Copy the metadata
    out_meta = sources[0].meta.copy()

    # Update the metadata
    out_meta.update({"driver": "GTiff",
                     "height": mosaic.shape[1],
                     "width": mosaic.shape[2],
                     "transform": out_trans})
    with rasterio.open(outfile, "w", **out_meta) as dest:
        dest.write(mosaic)
    return outfile_name


# def cog_gdal(in_file, cog_file, ovr_file="", delete_source=False, overwrite=False):
#     # TODO: check usefulness of this function, considering this cogging process generates validation errors when checking with rio_cogeo's cog_validate
#     in_file, cog_file, ovr_file = str(in_file), str(cog_file), str(ovr_file)  # in case they are Path objects
#     if not Path(cog_file).is_file() or overwrite:
#         os.system("gdalinfo --version")
#         print("gdal_translate #1 ...")
#         # WARNING: some paths may contain spaces. Always surround paths with "" in command line as below
#         os.system("gdal_translate -of GTiff -co TILED=YES -co BIGTIFF=YES -co COMPRESS=LZW \"" + in_file + "\" \"" + cog_file + "\"")
#         print("Done gdal_translate #1; gdaladdo ...")
#         os.system("gdaladdo -r average \"" + cog_file + "\" 2 4 8 16 32")
#         print("Done gdaladdo; gdal_translate #2 ...")
#         if Path(cog_file).is_file() and delete_source:
#             print("Deleting " + in_file.split('\\')[-1] + "\n")
#             os.remove(in_file)
#     else:
#         print("COG file " + cog_file + " already exists. Aborting coggification process...\n")