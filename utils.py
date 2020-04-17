import argparse
import csv
import glob
from pathlib import Path
import os
from datetime import datetime
import warnings
from typing import Union
import logging

from ruamel_yaml import YAML
import rasterio

logging.getLogger(__name__)

class CsvLogger:
    def __init__(self, out_csv: str = None):
        self.out_csv = out_csv
        if self.out_csv:
            self.create_csv(out_csv)
        self.switch = False

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

    def write_row(self, row=[]):
        if self.out_csv:
            try:
                of_connection = open(str(self.out_csv), 'a', newline="")  # Write to the csv file ('a' means append)
                writer = csv.writer(of_connection, delimiter=';')
                writer.writerow(row)
                of_connection.close()
            except PermissionError as e:
                logging.warning(e)
        else:
            if not self.switch:
                logging.warning("Output was not created. Use self.create_csv() method to create csv.")
            self.switch = True


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
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def empty_folder(folder):
    files = glob.glob('%s/*' % folder)
    for f in files:
        os.remove(f)
        warnings.warn('Removing: %s' % f)


def validate_raster(raster: Union[Path, str]):
    # This would have been great if it worked. See: https://lists.osgeo.org/pipermail/gdal-dev/2013-November/037520.html
    # Been having trouble with Gdal 2.2.2: not reading ntf.
    # Also, version 2.4 is returning invalid ntf, although open wells in QGIS
    # if Path(raster).is_file():
    #     ds = gdal.Open(str(raster))
    #     for i in range(ds.RasterCount):
    #         ds.GetRasterBand(1).Checksum()
    #         if gdal.GetLastErrorType() != 0:
    #             return False
    pass


def valid_path_length(path: Union[Path, str]):
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
    path = Path(path)
    if path.is_file():
        return True
    else:
        valid_path_length(path)
        return False


def rasterio_raster_reader(tif_file=""):
    raster = rasterio.open(str(tif_file), 'r')
    return raster


def list_of_tuples_from_csv(path, delimiter=";"):
    assert Path(path).suffix == '.csv', ('Not a ".csv.": ' + path)
    with open(str(path), newline='') as f:
        reader = csv.reader(f, delimiter=delimiter)
        data = [tuple(row) for row in reader]
    return data


def log_csv(out_file, row=[]):
    of_connection = open(str(out_file), 'a', newline="")  # Write to the csv file ('a' means append)
    writer = csv.writer(of_connection, delimiter=';')
    writer.writerow(row)
    of_connection.close()