import argparse
from pathlib import Path
from preprocess_glob import tile_list_glob, ImageInfo
from utils import read_parameters
import glob
from dataclasses import dataclass
import rasterio
import numpy as np


@dataclass
class ImgError:
    img_name: str
    detected_error: str


@dataclass
class ImgValidated:
    img_name: str
    bands_info:dict
    b_info: list = None
    g_info: list = None
    r_info: list = None
    n_info: list = None

# Validation steps for the preprocess pipeline.
def main(input_csv: str = "",
         method: str = "otb-bayes",
         max_ram: int = 4096,
         log_csv: str = "",
         overwrite: bool = False,
         glob_params: dict = None,
         dry_run: bool = False,
         delete_intermediate_files: bool = False):

    pansharp_glob_list = tile_list_glob(**glob_params)

    # Group tiles per image.
    unique_values = set([(tile.parent_folder, tile.image_folder, tile.prep_folder, tile.mul_xml) for tile in pansharp_glob_list])
    list_img = []
    for elem in unique_values:
        image_info = ImageInfo(parent_folder=elem[0], image_folder=elem[1], prep_folder=elem[2], tile_list=[], mul_xml=elem[3])
        list_img.append(image_info)

    for img in list_img:
        bgrn_dict = {'B': '', 'G': '', 'R': '', 'N': ''}
        error_list = []
        lst_img = [name for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        for b in bgrn_dict.keys():
            p = rf"_uint8_BAND_{b}.tif"
            bgrn_dict[b] = [el for el in lst_img if el.endswith(p)][0]

        img_info = ImgValidated(img_name=str(img.image_folder), bands_info={'B':[], 'G':[], 'R': [], 'N': []})
        for key, val in bgrn_dict.items():
            if val:
                with rasterio.open(val, 'r') as dst:
                    array = dst.read()
                    info_list = [np.min(array), np.max(array), np.mean(array), np.std(array)]
                    img_info.bands_info[key] = info_list
            else:
                err_img = ImgError(img_name=str(img.image_folder), detected_error=f"Could not locate all 4 BGRN tif files")
                error_list.append(err_img)
                break
        print(img_info.bands_info)

        boubou = 1
            # b_file = img.parent_folder / img.image_folder / img.prep_folder / Path(b_name)
# Validate existance of B-G-R-N files.

# Get min max mean values (assert they are not saturated).

# Output validation table
# image name, BGRN min-max-mean-std values.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    main(**params['process'], glob_params=params['glob'])
