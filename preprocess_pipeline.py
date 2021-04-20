import os
import argparse
from datetime import datetime
from pathlib import Path
import glob
from tqdm import tqdm

from PansharpRaster import pansharpen
from utils import read_parameters, CsvLogger
from preprocess_glob import tile_list_glob, ImageInfo, list_of_tiles_from_csv
from PansharpRaster import rasterio_merge_tiles, gdal_split_band


def main(input_csv: str = "",
         method: str = "otb-bayes",
         max_ram = 4096,
         log_csv: str = "",
         overwrite: bool = False,
         glob_params: dict = None,
         dry_run: bool = False,
         delete_intermediate_files: bool = False):
    """
    Preprocess rasters according to chosen parameters. This includes pansharpening,
    rescaling to 8bit, merging tiles and splitting rasters into single band images.
    :param input_csv: str
        Csv from glob process, if glob was done as separate step.
    :param method: str
        Pansharp method. Choices: otb-lmvm, otb-bayes, simple_brovey, brovey, simple_mean, esri, hsv
    :param log_csv: str
        Name of csv where logging for individual rasters (ie one raster per row) will be recorded
    :param overwrite: bool
        If True, all existing files are overwritten. Careful!
    :param glob_params: dict (or equivalent returned from yaml file)
        Parameters sent to preprocess_glob.pansharp_glob() function. See function for more details.
    :param dry_run: bool
        If True, script runs normally, except all time-consuming processes are skipped (i.e. no pansharp, no cogging)
    :return:
        Preprocessed rasters (pansharped/cogged), depending on inputted parameters and
        availability of modules (eg. otbApplication and rio_cogeo)
    """

    base_dir = glob_params['base_dir']
    os.chdir(base_dir)

    import logging.config  # based on: https://stackoverflow.com/questions/15727420/using-logging-in-multiple-modules
    out_log_path = Path("./logs")
    out_log_path.mkdir(exist_ok=True)
    logging.config.fileConfig(log_config_path)  # See: https://docs.python.org/2.4/lib/logging-config-fileformat.html
    logging.info("Started")

    if dry_run:
        logging.warning("DRY-RUN")

    CsvLog = CsvLogger(out_csv=log_csv, info_type='log')

    # 1. BUILD INPUT LIST
    ################################################################################
    # if input csv specified, build input list from it, else use pansharp_glob() function and glob parameters
    if input_csv:
        pansharp_glob_list = list_of_tiles_from_csv(input_csv, delimiter=";")
    else:
        pansharp_glob_list = tile_list_glob(**glob_params)

    # 2. LOOP THROUGH INPUT LIST. Each item is a row with info about single image (multispectral/panchromatic, etc.)
    ################################################################################
    for tile_img in tqdm(pansharp_glob_list, desc='Iterating through mul/pan pairs list'):
        now_read, duration = datetime.now(), 0
        os.chdir(base_dir)

        # 3. PANSHARP!
        ################################################################################
        if 'psh' in tile_img.process_steps:
            # then pansharp
            tile_img.last_processed_fp, err = pansharpen(tile_info=tile_img, method=method, ram=max_ram, dry_run=dry_run, overwrite=overwrite)
            tile_img.errors = err if err != '[]' else None

        if 'scale' in tile_img.process_steps and not tile_img.errors:
            # then scale to uint8.
            from PansharpRaster import gdal_8bit_rescale
            tile_img.last_processed_fp, err = gdal_8bit_rescale(tile_img, overwrite=overwrite)
            tile_img.errors = err if err else None

        if tile_img.last_processed_fp is None and tile_img.psh_tile and not tile_img.errors:
            # Means that the original tile is already pansharpened and 8bit.
            tile_img.last_processed_fp = tile_img.parent_folder / tile_img.image_folder / tile_img.psh_tile

        logging.info(f"Tile {tile_img.last_processed_fp.name} processed in {(datetime.now() - now_read).seconds / 60} minutes")

    # Group tiles per image.
    unique_values = set([(tile.parent_folder, tile.image_folder, tile.prep_folder, tile.mul_xml) for tile in pansharp_glob_list])
    list_img = []
    for elem in unique_values:
        image_info = ImageInfo(parent_folder=elem[0], image_folder=elem[1], prep_folder=elem[2], tile_list=[], mul_xml=elem[3])

        for tile in pansharp_glob_list:
            if tile.image_folder == image_info.image_folder:
                image_info.tile_list.append(tile.last_processed_fp)
                if tile.errors and not image_info.errors:
                    err_msg = f"One or more tile in image {image_info.image_folder} has error during pansharpening or scaling operation. " \
                              f"Will not proceed with merge."
                    image_info.errors = err_msg
        list_img.append(image_info)

    for img in tqdm(list_img, desc='Merge tiles and split into singleband images'):
        now_read, duration = datetime.now(), 0
        if not img.errors:
            if len(img.tile_list) > 1:
                img.merge_img_fp, img.errors = rasterio_merge_tiles(img, overwrite=overwrite)
            else:
                img.merge_img_fp = img.tile_list[0]
        else:
            logging.warning(img.errors)

        if not img.errors:
            # split into 1 band/tif file
            img.band_file_list, img.errors = gdal_split_band(img)
        else:
            logging.warning(img.errors)

        if delete_intermediate_files and not img.errors:
            logging.warning('Will delete intermediate files.')
            patern = str(img.parent_folder / img.image_folder / img.prep_folder / Path('*.tif'))
            list_file_to_delete = [f for f in glob.glob(patern) if f not in img.band_file_list]
            for file in list_file_to_delete:
                try:
                    os.remove(file)
                except OSError as e:
                    print("Error: %s : %s" % (file, e.strerror))

        duration = (datetime.now() - now_read).seconds / 60
        logging.info(f"Image {img.image_folder} processed in {duration} minutes")
        row = [str(img.image_folder), ','.join(str(el) for el in img.band_file_list), img.errors, str(duration)]

        CsvLog.write_row(info=row)

    list_16bit = [x for x in pansharp_glob_list if x.dtype == "uint16"]
    list_8bit = [x for x in pansharp_glob_list if x.dtype == "uint8"]

    existing_pshps = [x for x in pansharp_glob_list if x.psh_tile]
    non_tiled = [x for x in list_img if x.tile_list == 1]

    logging.info(
        f"\n*** Tiles ***"
        f"\nProcessed tiles: {len(pansharp_glob_list)}"
        f"\n\tPansharpened: {len(pansharp_glob_list) - len(existing_pshps)}"
        f"\n\tAlready pansharpened: {len(existing_pshps)}"
        f"\n\t16 bit: {len(list_16bit)}"
        f"\n\t8 bit: {len(list_8bit)}"
        f"\n\n*** Images ***"
        f"\nProcessed images: {len(list_img)}"
        f"\n\tMerged: {len(list_img) - len(non_tiled)}"
        f"\n\tNon tiled images: {len(non_tiled)}"
          )

    logging.info("Finished")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pansharp execution')
    parser.add_argument('param_file', metavar='DIR',
                        help='Path to preprocessing parameters stored in yaml')
    args = parser.parse_args()
    config_path = Path(args.param_file)
    params = read_parameters(args.param_file)

    log_config_path = Path('logging.conf').absolute()

    main(**params['process'], glob_params=params['glob'])
