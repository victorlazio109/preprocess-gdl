import os
import argparse
from _ast import List
from datetime import datetime
from pathlib import Path
from typing import Union

from tqdm import tqdm

from PansharpRaster import PansharpRaster
from utils import list_of_tuples_from_csv, read_parameters, validate_file_exists, CsvLogger
from preprocess_glob import pansharp_glob


def main(input_csv: str = "",
         method: str ="bayes",
         trim: Union[int, List] = 0,
         copy_to_8bit: bool = True,
         max_ram = 4096,
         cog: bool = True,
         cog_inp_size_threshold = 14,
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
    :param copy_to_8bit: bool
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
    # FIXME: subprocess calls will not work if base_dir is of type UNC.

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
        pansharp_glob_list = list_of_tuples_from_csv(input_csv, delimiter=";")
    else:
        pansharp_glob_list = pansharp_glob(**glob_params, pansharp_method=method)

    count = ct_missing_mul_pan = count_pshped = ct_psh_exist = 0

    # 2. LOOP THROUGH INPUT LIST. Each item is a row with info about single image (multispectral/panchromatic, etc.)
    ################################################################################
    for row in tqdm(pansharp_glob_list, desc='Iterating through mul/pan pairs list'):
        now_read, duration = datetime.now(), 0
        # Map each item of row to a intelligible variable
        base_dir, mul_raster, pan_raster, dtype, output_psh, psh_method_csv, output_cog, *_ = [row[i] for i in range(len(row))]
        # Create instance of PansharpRaster from these infos. To be completed during process.
        PshRaster = PansharpRaster(basedir=Path(base_dir),
                                   multispectral=Path(mul_raster),
                                   panchromatic=Path(pan_raster),
                                   dtype=dtype,
                                   method=method,
                                   trim=trim,
                                   copy_to_8bit=copy_to_8bit,
                                   cog_delete_source=cog_delete_source)
        os.chdir(base_dir)
        logging.debug(f"Output pansharp: {output_psh}")

        # 3. PANSHARP!
        ################################################################################
        # TODO: standardize flow of pansharpen() and coggify(). Many validation steps are done internally for coggify(),
        # like making sure output doens't exist, input exists, etc.
        if not validate_file_exists(Path(output_cog)):
            # If output not found, check if all inputs exist before processing, else skip (already exists).
            if not validate_file_exists(Path(output_psh)) or overwrite:
                # Double check if multispectral or panchromatic are not valid rasters, raise warning and skip.
                if not validate_file_exists(PshRaster.multispectral) or not validate_file_exists(PshRaster.panchromatic):
                    logging.warning('Missing info for mul %s or pan %s raster.',
                                   PshRaster.multispectral, PshRaster.panchromatic)
                    continue
                else:  # Else: then pansharp does not exist and mul/pan files are valid --> PANSHARP!
                    Path(output_psh).parent.mkdir(exist_ok=True)
                    PshRaster.pansharpen(output_psh, ram=max_ram, dry_run=dry_run)
            else:  # Else: pansharp exists.
                logging.info(f"\nPansharp already exists: {output_psh}")
                PshRaster.pansharp = Path(output_psh)
        else:
            logging.info(f"\nCogged pansharp already exists: {output_cog}")
            PshRaster.cog = Path(output_cog)
            PshRaster.cog_size = round(Path(output_cog).stat().st_size / 1024 ** 3, 2)

        duration = (datetime.now() - now_read).seconds / 60

        # 4. COGGIFY!
        if cog:
            PshRaster.coggify(output_cog,
                              inp_size_threshold=cog_inp_size_threshold,
                              dry_run=dry_run,
                              overwrite=overwrite,
                              delete_source=cog_delete_source)

        # 5. UINT8 COPY, if requested and dtype is uint16
        # set name for 8bit copy: replace "uint16" with "uint8" if possible, else add the latter as suffix.
        if "uint16" in output_psh:
            out_8bit = output_psh.replace("uint16", "uint8")
            output_cog_8bit = output_cog.replace("uint16", "uint8")
        else:
            out_8bit = str(Path(output_psh).parent / f"{Path(output_psh).stem}-uint8{Path(output_psh).suffix}")
            output_cog_8bit = str(Path(output_cog).parent / f"{Path(output_cog).stem}-uint8{Path(output_cog).suffix}")

        if not validate_file_exists(output_cog_8bit):
            if copy_to_8bit and PshRaster.dtype == "uint16":
                if not validate_file_exists(out_8bit) or overwrite:  # If 8bit copy does not exist, create it!
                    PshRaster.rescale_trim(out_8bit, dry_run=dry_run)
                else:
                    PshRaster.pansharp_8bit_copy = Path(out_8bit)

                if cog:
                    PshRaster.coggify(out_file=output_cog_8bit,
                                      inp_size_threshold=cog_inp_size_threshold,
                                      uint8_copy=True,
                                      dry_run=dry_run,
                                      overwrite=overwrite,
                                      delete_source=cog_delete_source)
        else:
            logging.info(f"\nCogged 8bit copy of pansharp already exists: {output_cog_8bit}")
            PshRaster.cog_8bit_copy = Path(output_cog_8bit)

            duration = datetime.now() - now_read

        # 5. Write metadata to CSV
        ################################################################################
        row = [PshRaster.multispectral, PshRaster.panchromatic, PshRaster.dtype, PshRaster.pansharp,
               PshRaster.pansharp_8bit_copy, PshRaster.cog, PshRaster.cog_8bit_copy, PshRaster.cog_size,
               now_read.strftime("%Y-%m-%d_%H-%M"), duration, PshRaster.errors]

        CsvLog.write_row(row=row)

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