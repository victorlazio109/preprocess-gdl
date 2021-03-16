import argparse
import csv
import glob
from pathlib import Path
import os
from datetime import datetime
import warnings
from typing import Union, List
import logging

from ruamel_yaml import YAML
import rasterio

logging.getLogger(__name__)


class CsvLogger:
    def __init__(self, out_csv: str = None, info_type: str = 'tile'):
        """
        Instanciate a CSV Logger
        :param out_csv: str
            Path to output csv that is to be created.
        """
        self.out_csv = out_csv
        if self.out_csv:
            self.create_csv(out_csv)
        self.switch = False

        supp_types = ['tile', 'log']
        if info_type in supp_types:
            self.info_type = info_type
        else:
            raise ValueError(f"Provided information type to CSVLogger isn't supported. Supported values are: {str(supp_types)}")

    def create_csv(self, path_to_csv=""):
        if path_to_csv:
            path_to_csv = Path(path_to_csv)
            if not path_to_csv.suffix == ".csv":
                logging.warning(f"Invalid output csv name: {path_to_csv}")
                return
            path_to_csv.parent.mkdir(exist_ok=True)
            if path_to_csv.is_file():
                path_to_csv = path_to_csv.parent / f"{path_to_csv.stem}_{datetime.now().strftime('%Y-%m-%d_%H-%M')}{path_to_csv.suffix}"
            try:
                open(str(path_to_csv), 'w', newline="")
            except PermissionError as e:
                logging.warning(e)
            self.out_csv = path_to_csv
            logging.info(f"{self.out_csv.name} will be saved to: {self.out_csv.parent.absolute()}")
        else:
            logging.warning("Csv output file not created.")

    def write_row(self, info):
        """
        Write a row to self.
        :param tile: TileInfo
            tile information to be added to the csv linked to self (self.out_csv)
        :return:
        """
        if self.out_csv:
            try:
                of_connection = open(str(self.out_csv), 'a', newline="")  # Write to the csv file ('a' means append)
                writer = csv.writer(of_connection, delimiter=';')
                if self.info_type == 'tile':
                    row = self.tile_to_row(info)
                else:
                    row = info
                writer.writerow(row)
                of_connection.close()
            except PermissionError as e:
                logging.warning(e)
        else:
            if not self.switch:
                logging.warning("Output was not created. Use self.create_csv() method to create csv.")
            self.switch = True

    def tile_to_row(self, tile):
        process_steps = ",".join(tile.process_steps)
        mul_pan_patern = ",".join([str(elem) for elem in tile.mul_pan_patern])
        row = [str(tile.parent_folder), process_steps, tile.dtype, str(tile.image_folder), mul_pan_patern,
               str(tile.mul_tile), str(tile.pan_tile), str(tile.psh_tile), str(tile.prep_folder), str(tile.last_processed_fp)]
        return row


def read_parameters(param_file):
    """Read and return parameters in .yaml file
    Args:
        param_file: Full file path of the parameters file
    Returns:
        YAML (Ruamel) CommentedMap dict-like object
    """
    yaml = YAML()
    with open(param_file) as yamlfile:
        params = yaml.load(yamlfile)
    return params


def str2bool(v):
    """
    Convert str to bool for inputted parameters (e.g. from argparse)
    :param v: str
        Input string to be converted to bool
    :return:
    """
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def empty_folder(folder):
    """
    Empty folder of all its files
    :param folder: str
        Path to folder to be emptied
    :return:
    """
    files = glob.glob('%s/*' % folder)
    for f in files:
        os.remove(f)
        logging.warning('Removing: %s' % f)


def validate_raster(raster: Union[Path, str]):
    # TODO: This would have been great if it worked. See: https://lists.osgeo.org/pipermail/gdal-dev/2013-November/037520.html
    # Been having trouble with Gdal 2.2.2: not reading ntf.
    # Also, version 2.4 is returning invalid ntf, although opens ok in QGIS.
    # if Path(raster).is_file():
    #     ds = gdal.Open(str(raster))
    #     for i in range(ds.RasterCount):
    #         ds.GetRasterBand(1).Checksum()
    #         if gdal.GetLastErrorType() != 0:
    #             return False
    pass


def valid_path_length(path: Union[Path, str]):
    """
    Validate path length is below limit for Windows file system.
    :param path: Path or str
        path to be validated
    :return: bool
    """
    path = Path(path)
    if os.name == "nt" and len(str(path.absolute())) >= 260:
        logging.warning('Path exceeds 260 characters. May cause problems on Windows, '
                        'e.g. file not found by python: %s', str(path.absolute()))
        # if len(sorted(Path(path).parent.glob(f"*{path.name}"))) == 1:  # FIXME: dirty workaround, but it works!
        #     return True
        # else:
        #     return False
        return False
    else:
        return True


def validate_file_exists(path: Union[Path, str]):
    """
    Checks if file exists, taking into account the path length limits on Windows
    :param path: Path or str
        Path to input file
    :return: bool
    """
    if not path:
        return False
    else:
        path = Path(path)
        if path.is_file():
            return True
        else:
            valid_path_length(path)
            return False


def rasterio_raster_reader(tif_file: str = ""):
    """
    Read raster
    :param tif_file: str
        Path to raster to be read
    :return: DatasetReader object (rasterio)
    """
    raster = rasterio.open(str(tif_file), 'r')
    return raster


# def list_of_tiles_from_csv(path, delimiter=";"):
#     """
#     Create list of tuples from a csv file
#     :param path: Path or str
#         path to csv file
#     :param delimiter: str
#         type of delimiter for inputted csv
#     :return:
#     """
#     assert Path(path).suffix == '.csv', ('Not a ".csv.": ' + path)
#     with open(str(path), newline='') as f:
#         reader = csv.reader(f, delimiter=delimiter)
#         # data = [tuple(row) for row in reader]
#         data = []
#         for row in reader:
#             mul_tile = Path(row[5]) if row != 'None' else None
#             pan_tile = Path(row[6]) if row != 'None' else None
#             psh_tile = Path(row[7]) if row != 'None' else None
#             last_processed_fp = Path(row[9]) if row != 'None' else None
#
#             tile = TileInfo(parent_folder=Path(row[0]), process_steps=list(row[1]), dtype=row[2], image_folder=Path(row[3]),
#                             mul_pan_patern=list(row[4]), mul_tile=mul_tile, pan_tile=pan_tile, psh_tile=psh_tile,
#                             prep_folder=Path(row[8]), last_processed_fp=last_processed_fp)
#             data.append(tile)
#     return data
