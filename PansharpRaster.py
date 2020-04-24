import os
from pathlib import Path
from typing import Union, List
import logging

import rasterio

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

    def pansharpen(self,
                   output_psh: str,
                   ram: int = 4096,
                   dry_run: bool = False):
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
        if not (self.multispectral.is_file() or self.panchromatic.is_file()):
            missing_mul_pan = f"Unable to pansharp due to missing mul {self.multispectral} or pan {self.panchromatic}"
            logging.warning(missing_mul_pan)
            self.errors.append(missing_mul_pan)

            return
        # Choose between otb or numpy methods.
        if self.method.startswith("otb-"):
            method = self.method.split("otb-")[-1] if self.method.startswith(
                "otb-") else self.method  # chop off -otb prefix if present
            from otb_apps import otb_pansharp, otb_8bit_rescale
            try:
                if not dry_run:
                    otb_pansharp(inp=str(self.panchromatic),
                                 inxs=str(self.multispectral),
                                 method=method,
                                 ram=ram,
                                 out=str(output_psh),
                                 out_dtype=self.dtype)
            except RuntimeError as e:
                logging.warning(e)
                self.errors.append(e)
                return
        elif self.method in ["simple_brovey", "brovey", "simple_mean", "esri", "hsv"]:
            try:
                from pansharp_numpy import pansharpen
            except ImportError as e:
                logging.warning(e)
                self.errors.append(e)
                return
            if not dry_run:
                pansharpen(str(self.multispectral), (str(self.panchromatic)), method=self.method)
        else:
            not_impl = f"Requested pansharp method {self.method} is not implemented"
            logging.warning(not_impl)
            self.errors.append(not_impl)

        if Path(output_psh).is_file():  # PansharpRaster object's attributes are defined as outputs are validated.
            self.pansharp = Path(output_psh)
            self.pansharp_size = round(self.pansharp.stat().st_size / 1024 ** 3)
        else:
            psh_fail = f"Failed to created pansharp: {output_psh}"
            logging.warning(psh_fail)
            self.errors.append(psh_fail)
        return

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
        if not dry_run:
            otb_8bit_rescale(infile=str(self.pansharp),
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


def cog_gdal(in_file, cog_file, ovr_file="", delete_source=False, overwrite=False):
    # TODO: check usefulness of this function, considering this cogging process generates validation errors when checking with rio_cogeo's cog_validate
    in_file, cog_file, ovr_file = str(in_file), str(cog_file), str(ovr_file)  # in case they are Path objects
    if not Path(cog_file).is_file() or overwrite:
        os.system("gdalinfo --version")
        print("gdal_translate #1 ...")
        # WARNING: some paths may contain spaces. Always surround paths with "" in command line as below
        os.system("gdal_translate -of GTiff -co TILED=YES -co BIGTIFF=YES -co COMPRESS=LZW \"" + in_file + "\" \"" + cog_file + "\"")
        print("Done gdal_translate #1; gdaladdo ...")
        os.system("gdaladdo -r average \"" + cog_file + "\" 2 4 8 16 32")
        print("Done gdaladdo; gdal_translate #2 ...")
        if Path(cog_file).is_file() and delete_source:
            print("Deleting " + in_file.split('\\')[-1] + "\n")
            os.remove(in_file)
    else:
        print("COG file " + cog_file + " already exists. Aborting coggification process...\n")