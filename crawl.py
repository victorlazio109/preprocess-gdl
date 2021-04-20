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