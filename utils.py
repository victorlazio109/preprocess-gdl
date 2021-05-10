import argparse
import csv
import glob
from pathlib import Path
import os
from datetime import datetime
from typing import Union
import logging

from ruamel_yaml import YAML
import rasterio

logging.getLogger(__name__)


class CsvLogger:
    def __init__(self, out_csv: str = None):
        """
        Instanciate a CSV Logger
        :param out_csv: str
            Path to output csv that is to be created.
        """
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

    def write_row(self, info):
        """
        Write a row to self.
        :param info:
            tile information to be added to the csv linked to self (self.out_csv)
        :return:
        """
        if self.out_csv:
            try:
                of_connection = open(str(self.out_csv), 'a', newline="")  # Write to the csv file ('a' means append)
                writer = csv.writer(of_connection, delimiter=';')
                writer.writerow(info)
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


def get_key_def(key, config, default=None, msg=None, delete=False, expected_type=None):
    """Returns a value given a dictionary key, or the default value if it cannot be found.
    :param key: key in dictionary (e.g. generated from .yaml)
    :param config: (dict) dictionary containing keys corresponding to parameters used in script
    :param default: default value assigned if no value found with provided key
    :param msg: message returned with AssertionError si length of key is smaller or equal to 1
    :param delete: (bool) if True, deletes parameter, e.g. for one-time use.
    :return:
    """
    if not config:
        return default
    elif isinstance(key, list):  # is key a list?
        if len(key) <= 1:  # is list of length 1 or shorter? else --> default
            if msg is not None:
                raise AssertionError(msg)
            else:
                raise AssertionError("Must provide at least two valid keys to test")
        for k in key:  # iterate through items in list
            if k in config:  # if item is a key in config, set value.
                val = config[k]
                if delete:  # optionally delete parameter after defining a variable with it
                    del config[k]
        val = default
    else:  # if key is not a list
        if key not in config or config[key] is None:  # if key not in config dict
            val = default
        else:
            val = config[key] if config[key] != 'None' else None
            if expected_type:
                assert isinstance(val, expected_type), f"{val} is of type {type(val)}, expected {expected_type}"
            if delete:
                del config[key]
    return val