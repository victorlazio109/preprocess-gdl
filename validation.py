import argparse
from pathlib import Path
from preprocess_glob import tile_list_glob, ImageInfo
from utils import read_parameters
import glob
from dataclasses import dataclass
import rasterio
from tqdm import tqdm
import numpy as np


@dataclass
class ImgError:
    img_name: str
    detected_error: str


@dataclass
class ImgValidated:
    img_name: str
    bands_info: dict


def err_to_table(err_list):
    str_log = f"*** List of images with errors and the detected error ***\n"
    for im in err_list:
        im_log = f"\t{im.img_name}  --->" \
                 f"\t{im.detected_error}\n"

        str_log += im_log
    print(str_log)


def val_to_table(val_list):
    str_log = f"*** Statistics for Validated Images ***\n" \
              f"Image name and per band [min, max, mean, std]"
    for im in val_list:
        img_log = f"\n\t{im.img_name}\n" \
                  f"\t\t\tBlue: {im.bands_info['B']}\n" \
                  f"\t\t\tGreen: {im.bands_info['G']}\n" \
                  f"\t\t\tRed: {im.bands_info['R']}\n" \
                  f"\t\t\tNIR: {im.bands_info['N']}\n"
        str_log += img_log
    print(str_log)


# Validation steps for the preprocess pipeline.
def main(glob_params: dict = None):
    """
    Validate images from
    :param glob_params: dict (or equivalent returned from yaml file)
        Parameters sent to preprocess_glob.pansharp_glob() function. See function for more details.
    :return:
    """
    import logging.config  # based on: https://stackoverflow.com/questions/15727420/using-logging-in-multiple-modules
    out_log_path = Path("./logs")
    out_log_path.mkdir(exist_ok=True)
    logging.config.fileConfig(log_config_path)  # See: https://docs.python.org/2.4/lib/logging-config-fileformat.html
    logging.info("Validation Started")

    pansharp_glob_list = tile_list_glob(**glob_params)

    # Group tiles per image.
    unique_values = set([(tile.parent_folder, tile.image_folder, tile.prep_folder, tile.mul_xml) for tile in pansharp_glob_list])
    list_img = []
    for elem in tqdm(unique_values, desc='Preparing image list'):
        image_info = ImageInfo(parent_folder=elem[0], image_folder=elem[1], prep_folder=elem[2], tile_list=[], mul_xml=elem[3])
        list_img.append(image_info)

    for img in tqdm(list_img, desc='Iterating through images'):
        bgrn_dict = {'B': '', 'G': '', 'R': '', 'N': ''}
        error_list = []
        val_list = []
        lst_img = [name for name in glob.glob(str(img.parent_folder / img.image_folder / img.prep_folder) + "/*.tif")]
        for b in bgrn_dict.keys():
            p = rf"_uint8_BAND_{b}.tif"
            bgrn_dict[b] = [el for el in lst_img if el.endswith(p)][0]

        img_info = ImgValidated(img_name=str(img.image_folder), bands_info={'B': [], 'G': [], 'R': [], 'N': []})
        for key, val in bgrn_dict.items():
            if val:
                with rasterio.open(val, 'r') as dst:
                    err_img = None
                    if not dst.crs:
                        err_img = ImgError(img_name=str(img.image_folder), detected_error=f"No CRS found")
                        error_list.append(err_img)
                        break
                    elif dst.dtypes[0] != 'uint8':
                        err_img = ImgError(img_name=str(img.image_folder), detected_error=f"Image dtype is {dst.dtype}")
                        error_list.append(err_img)
                        break
                    else:
                        array = dst.read()
                        info_list = [np.min(array), np.max(array), round(float(np.mean(array)), 2), round(float(np.std(array)), 2)]
                        img_info.bands_info[key] = info_list

            else:
                err_img = ImgError(img_name=str(img.image_folder), detected_error=f"Could not locate all 4 BGRN tif files")
                error_list.append(err_img)
                break
        if not err_img:
            val_list.append(img_info)

        err_to_table(error_list)
        val_to_table(val_list)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    main(glob_params=params['glob'])
