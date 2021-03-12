import os
import argparse
from _ast import List
from datetime import datetime
from pathlib import Path
from typing import Union

from tqdm import tqdm

from PansharpRaster import PansharpRaster, pansharpen
from utils import list_of_tuples_from_csv, read_parameters, validate_file_exists, CsvLogger
from preprocess_glob import pansharp_glob, ImageInfo


def main(input_csv: str = "",
         method: str = "otb-bayes",
         trim: Union[int, List] = 0,
         to_8bit: bool = True,
         max_ram = 4096,
         cog: bool = True,
         cog_delete_source: bool = False,
         log_csv: str = "",
         overwrite: bool = False,
         glob_params: dict = None,
         dry_run: bool = False):
    """
    Preprocess rasters according to chosen parameters. This includes pansharpening,
    rescaling with radiometric histogram trimming and cogging rasters.
    #FIXME: trim function is not implemented other than for uint8 copies since only these copies are processed with the DynamicConvert app
    :param input_csv: str
        Csv from glob process, if glob was done as separate step.
    :param method: str
        Pansharp method. Choices: otb-lmvm, otb-bayes, simple_brovey, brovey, simple_mean, esri, hsv
    :param trim: int or list
        Quantiles to cut from histogram low/high values.
    :param to_8bit: bool
        Create uint8 copy of all outputted pansharps and cogs if input's dtype is uint16
    :param cog: bool
        If True, coggify outputted pansharps (requires rio_cogeo)
    :param cog_delete_source: bool
        If True, non-cog pansharp will be deleted after cog pansharp is created and validated
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

    CsvLog = CsvLogger(out_csv=log_csv)

    # 1. BUILD INPUT LIST
    ################################################################################
    # if input csv specified, build input list from it, else use pansharp_glob() function and glob parameters
    if input_csv:
        # TODO: Review list_of_tuples_from_csv function to fit pansharp_glob_list 's output.
        pansharp_glob_list = list_of_tuples_from_csv(input_csv, delimiter=";")
    else:
        pansharp_glob_list = pansharp_glob(**glob_params, pansharp_method=method)

    # count = ct_missing_mul_pan = count_pshped = ct_psh_exist = 0

    # 2. LOOP THROUGH INPUT LIST. Each item is a row with info about single image (multispectral/panchromatic, etc.)
    ################################################################################
    for tile_img in tqdm(pansharp_glob_list, desc='Iterating through mul/pan pairs list'):
        now_read, duration = datetime.now(), 0
        os.chdir(base_dir)
        # logging.debug(f"Output pansharp: {output_psh}")

        # 3. PANSHARP!
        ################################################################################
        if 'psh' in tile_img.process_steps:
            # then pansharp
            toto = 1
            tile_img.last_processed_fp = pansharpen(tile_info=tile_img, method=method, ram=max_ram, dry_run=dry_run, overwrite=overwrite)

        duration = (datetime.now() - now_read).seconds / 60

        if 'scale' in tile_img.process_steps:
            # then scale to uint8.
            from PansharpRaster import gdal_8bit_rescale
            tile_img.last_processed_fp = gdal_8bit_rescale(tile_img)

    # Group tiles per image.
    unique_values = set([(tile.parent_folder, tile.image_folder, tile.prep_folder) for tile in pansharp_glob_list])
    list_img = []
    for elem in unique_values:
        image_info = ImageInfo(parent_folder=elem[0], image_folder=elem[1], prep_folder=elem[2], tile_list=[])

        for tile in pansharp_glob_list:
            if tile.image_folder == image_info.image_folder:
                image_info.tile_list.append(tile.last_processed_fp)
        list_img.append(image_info)

    from PansharpRaster import rasterio_merge_tiles
    for img in list_img:
        if len(img.tile_list) > 1:
            img.merge_img_fp = rasterio_merge_tiles(img)
        else:
            img.merge_img_fp = img.tile_list[0]


        # # 4. COGGIFY!
        # if cog:
        #     PshRaster.coggify(output_cog,
        #                       dry_run=dry_run,
        #                       overwrite=overwrite,
        #                       delete_source=cog_delete_source)
        #
        # # 5. UINT8 COPY, if requested and dtype is uint16
        # # set name for 8bit copy: replace "uint16" with "uint8" if possible, else add the latter as suffix.
        # if "uint16" in output_psh:
        #     out_8bit = output_psh.replace("uint16", "uint8")
        # else:
        #     out_8bit = str(Path(output_psh).parent / f"{Path(output_psh).stem}-uint8{Path(output_psh).suffix}")
        #
        # if "uint16" in output_cog:
        #     output_cog_8bit = output_cog.replace("uint16", "uint8")
        # else:
        #     output_cog_8bit = str(Path(output_cog).parent / f"{Path(output_cog).stem}-uint8{Path(output_cog).suffix}")
        #
        # # If cogged 8bit copy doesn't exist
        # if not validate_file_exists(output_cog_8bit):
        #     # if 8bit is requested and pansharp is 16bit
        #     if copy_to_8bit and PshRaster.dtype == "uint16":
        #         # if output 8bit pansharp doesn't exist or overwrite requested, RESCALE!
        #         if not validate_file_exists(out_8bit) or overwrite:
        #             PshRaster.rescale_trim(out_8bit, dry_run=dry_run)
        #         else:
        #             PshRaster.pansharp_8bit_copy = Path(out_8bit)
        # else:
        #     logging.info(f"\nCogged 8bit copy of pansharp already exists: {output_cog_8bit}")
        #     PshRaster.cog_8bit_copy = Path(output_cog_8bit)
        #
        # if cog:
        #     PshRaster.coggify(out_file=output_cog_8bit,
        #                       uint8_copy=True,
        #                       dry_run=dry_run,
        #                       overwrite=overwrite,
        #                       delete_source=cog_delete_source)
        #
        #     duration = datetime.now() - now_read
        #
        # # 5. Write metadata to CSV
        # ################################################################################
        # row = [PshRaster.multispectral, PshRaster.panchromatic, PshRaster.dtype, PshRaster.pansharp,
        #        PshRaster.pansharp_8bit_copy, PshRaster.cog, PshRaster.cog_8bit_copy, PshRaster.cog_size,
        #        now_read.strftime("%Y-%m-%d_%H-%M"), duration, PshRaster.errors]
        #
        # CsvLog.write_row(row=row)

    list_16bit = [x for x in PshRaster.all_objects if x.dtype == "uint16"]
    list_8bit = [x for x in PshRaster.all_objects if x.dtype == "uint8"]

    existing_pshps = [x for x in PshRaster.all_objects if x.pansharp]
    existing_cogs = [x for x in PshRaster.all_objects if x.cog]

    logging.info(
        f"\nProcessed rasters: {len(PshRaster.all_objects)}"
          f"\n\t16 bit: {len(list_16bit)}"
          f"\n\t8 bit: {len(list_8bit)}"
        f"\n\n*** COG pansharps ***"
          f"\nExisting cog pansharps: {len(existing_cogs)}"
          f"\n\t16 bit: {len([x for x in existing_cogs if x.dtype == 'uint16'])}"
          f"\n\t\t8 bit copy: {len([x for x in PshRaster.all_objects if x.cog_8bit_copy])}"
          f"\n\t8 bit: {len([x for x in existing_cogs if x.dtype == 'uint8'])}"
        f"\n\n*** Non-COG pansharps ***"
          f"\nExisting non-cog pansharps: {len(existing_pshps)}"
          f"\n\t16 bit: {len([x for x in existing_pshps if x.dtype == 'uint16'])}"
          f"\n\t\t8 bit copy: {len([x for x in PshRaster.all_objects if x.pansharp_8bit_copy])}"
          f"\n\t8 bit: {len([x for x in existing_pshps if x.dtype == 'uint8'])}"
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

    main(**params['pansharp'], glob_params=params['glob'])