import logging
import os
import subprocess

logging.getLogger(__name__)

def otb_dtype_to_pixtype(out_dtype="uint8"):
    """
    Convert desired output datatype as string to corresponding int for use in otb apps.
    :param out_dtype: str
        Desired output datatype
    :return: output pixel type (int) as used by otb apps.
    """
    # Set output data type
    out_dtypes = ["uint8", "int16", "uint16", "int32", "uint32"]  # FIXME: may be ["uint8", "uint16", "int16", "uint32", "int32"]
    if out_dtype in out_dtypes:
        out_pix_type = out_dtypes.index(out_dtype)
    else:
        logging.warning("Invalid output datatype %s, defaulting to uint8" % out_dtype)
        out_pix_type = 0

    return out_pix_type


def otb_pansharp(inp, inxs, out, method="bayes", out_dtype="uint8", ram=1024):
    # See: https://www.orfeo-toolbox.org/CookBook/Applications/app_BundleToPerfectSensor.html
    try:
        import otbApplication  # Python >3.5 compatibility issues...
        app = otbApplication.Registry.CreateApplication("BundleToPerfectSensor")
        app.SetParameterString("inp", inp)
        app.SetParameterString("inxs", inxs)
        app.SetParameterString("method", method)
        app.SetParameterInt("ram", ram)
        app.SetParameterString("out", out)
        app.SetParameterOutputImagePixelType("out", otb_dtype_to_pixtype(out_dtype))
        app.ExecuteAndWriteOutput()
    except ImportError as e:
        logging.warning(e)

        # dirty workaround, but it works!
        command = f"otbcli_BundleToPerfectSensor " \
                  f"-inp \"{str(inp)}\" " \
                  f"-inxs \"{str(inxs)}\" " \
                  f"-method {str(method)} " \
                  f"-out \"{str(out)}\" {out_dtype} " \
                  f"-ram {str(ram)}"

        logging.debug(f"Trying to pansharp through command-line with following command: {command}")
        subproc = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if subproc.stderr:
            logging.warning(subproc.stderr)
            if "otbcli_BundleToPerfectSensor: not found" in subproc.stderr:
                logging.warning("Make sure the environment for OTB is initialized. "
                                "See: https://www.orfeo-toolbox.org/CookBook/Installation.html")

def otb_8bit_rescale(infile, outfile, ram=4096, trim_lower=2, trim_higher=2):
    # See: https://www.orfeo-toolbox.org/CookBook/Applications/app_DynamicConvert.html
    try:
        import otbApplication  # Python >3.5 compatibility issues...
        app = otbApplication.Registry.CreateApplication("DynamicConvert")

        app.SetParameterString("in", str(infile))
        app.SetParameterString("out", str(outfile))
        app.SetParameterString("type", "linear")
        app.SetParameterFloat("quantile.high", trim_higher)
        app.SetParameterFloat("quantile.low", trim_lower)
        app.SetParameterString("channels", "all")
        app.SetParameterFloat("outmin", 0)
        app.SetParameterFloat("outmax", 255)
        app.SetParameterOutputImagePixelType("out", 0)
        app.SetParameterInt("ram", ram)

        app.ExecuteAndWriteOutput()

    except ImportError as e:
        logging.warning(e)

        command = f"otbcli_DynamicConvert " \
                  f"-in \"{str(infile)}\" " \
                  f"-out \"{str(outfile)}\" " \
                  f"-type linear " \
                  f"-quantile.high {trim_higher} " \
                  f"-quantile.low {trim_lower} " \
                  f"-ram {str(ram)} " \
                  f"-channels all " \
                  f"-outmin 1 " \
                  f"-outmax 255"

        if os.name == "nt" and os.getcwd().startswith("\\"):  # If OS is Windows and working directory path is UNC
            logging.warning(f"Subprocess cannot execute cmd.exe if working directory is UNC type: {os.getcwd()}")
            # See: https://stackoverflow.com/questions/5187160/call-subprocess-popen-when-the-working-directory-is-on-a-unc-path-not-a-mappe
        else:
            logging.debug(f"Trying to rescale through command-line with following command: {command}")
            subproc = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if subproc.stderr:
                logging.warning(subproc.stderr)
                if "otbcli_DynamicConvert: not found" in subproc.stderr:
                    logging.warning("Make sure the environment for OTB is initialized. "
                                    "See: https://www.orfeo-toolbox.org/CookBook/Installation.html")
