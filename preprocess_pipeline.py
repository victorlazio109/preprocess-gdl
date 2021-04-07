import argparse
import glob
import os
import re
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from PansharpRaster import gdal_split_band, pansharpen, rasterio_merge_tiles, gdal_8bit_rescale
from preprocess_glob import ImageInfo, list_of_tiles_from_csv, tile_list_glob
from utils import CsvLogger, read_parameters


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
    for img_info in tqdm(pansharp_glob_list, desc='Iterating through mul/pan pairs list'):
        now_read, duration = datetime.now(), 0
        os.chdir(base_dir)

        # Merge has to be done first. Otherwise it will create artefacts in other steps.
        if 'merge' in img_info.process_steps:
            p = re.compile('R\wC\w')
            if 'psh' in img_info.process_steps:
                out_mul_name = p.sub('Merge', str(img_info.mul_tile_list[0].stem)) + ".tif"
                out_pan_name = p.sub('Merge', str(img_info.pan_tile_list[0].stem)) + ".tif"
                out_mul_merge = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path(out_mul_name)
                out_pan_merge = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path(out_pan_name)

                img_info.mul_merge, img_info.errors = rasterio_merge_tiles(tile_list=img_info.mul_tile_list, outfile=out_mul_merge,
                                                                           overwrite=overwrite)
                img_info.pan_merge, img_info.errors = rasterio_merge_tiles(tile_list=img_info.pan_tile_list, outfile=out_pan_merge,
                                                                           overwrite=overwrite)
            else:
                out_psh_name = p.sub('Merge', str(img_info.psh_tile_list[0].stem)) + ".tif"
                out_psh_merge = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path(out_psh_name)
                img_info.psh_merge, img_info.errors = rasterio_merge_tiles(tile_list=img_info.mul_tile_list, outfile=out_psh_merge,
                                                                           overwrite=overwrite)
        else:
            if 'psh' in img_info.process_steps:
                img_info.mul_merge = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path(img_info.mul_tile_list[0])
                img_info.pan_merge = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path(img_info.pan_tile_list[0])
            else:
                img_info.psh_merge = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path(img_info.psh_tile_list[0])

        # Pansharpening
        if 'psh' in img_info.process_steps:
            img_info.psh_merge, err = pansharpen(img_info=img_info, method=method, ram=max_ram, dry_run=dry_run, overwrite=overwrite)
            img_info.errors = err if err != '[]' else None

        # Scale to 8 bit
        if 'scale' in img_info.process_steps and not img_info.errors:
            # then scale to uint8.
            in_name = img_info.psh_merge.stem
            if str(in_name).endswith(f"_{img_info.dtype}"):
                outfile_name = Path(str(in_name).replace(f"_{img_info.dtype}", "_uint8.tif"))
            else:
                outfile_name = Path(f"{str(in_name)}_uint8.tif")
            outfile = img_info.parent_folder / img_info.image_folder / img_info.prep_folder / outfile_name
            err = gdal_8bit_rescale(infile=img_info.psh_merge, outfile=outfile, overwrite=overwrite)
            img_info.errors = err if err else None
            img_info.scale_img = outfile
        else:
            img_info.scale_img = img_info.psh_merge

        # Split into singleband images
        if not img_info.errors:
            img_info.band_file_list, img_info.errors = gdal_split_band(img_info.scale_img, img_info)

        # Delete intemerdiate files
        if delete_intermediate_files and not img_info.errors:
            logging.warning('Will delete intermediate files.')
            patern = str(img_info.parent_folder / img_info.image_folder / img_info.prep_folder / Path('*.tif'))
            list_file_to_delete = [f for f in glob.glob(patern) if f not in img_info.band_file_list]
            for file in list_file_to_delete:
                try:
                    os.remove(file)
                except OSError as e:
                    print("Error: %s : %s" % (file, e.strerror))

        duration = (datetime.now() - now_read).seconds / 60
        logging.info(f"Image {img_info.image_folder} processed in {duration} minutes")

        # CsvLog.write_row(info=row)

    list_16bit = [x for x in pansharp_glob_list if x.dtype == "uint16"]
    list_8bit = [x for x in pansharp_glob_list if x.dtype == "uint8"]

    existing_pshps = [x for x in pansharp_glob_list if x.psh_tile_list]
    non_tiled = [x for x in pansharp_glob_list if 'merge' not in x.process_steps]

    logging.info(
        f"\n*** Images ***"
        f"\nProcessed tiles: {len(pansharp_glob_list)}"
        f"\n\tPansharpened: {len(pansharp_glob_list) - len(existing_pshps)}"
        f"\n\tAlready pansharpened: {len(existing_pshps)}"
        f"\n\t16 bit: {len(list_16bit)}"
        f"\n\t8 bit: {len(list_8bit)}"
        f"\n\tMerged images: {len(pansharp_glob_list) - len(non_tiled)}"
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
