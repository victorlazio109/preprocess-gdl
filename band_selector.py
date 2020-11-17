import os
from pathlib import Path

base_dir = Path("/wspace/disk01/2btrees/imagerie/vancouver/054230029070_01")

glob_pattern = "*_P00?_PREP/*.TIF"

# make list of images to preprocess
globbed_imgs_paths = base_dir.glob(glob_pattern)


# loop through list
for img_path in globbed_imgs_paths:
    img_pathlib = Path(img_path)
    print(f"Input image: {img_pathlib}")
    # build output name of image
    out_img = f"{img_pathlib.parent}/{img_pathlib.stem}_BGRN.TIF"

    # gdal_translate with img_path and out_img name

    gdal_translate_cmd = f"gdal_translate -of GTiff  -b 2 -b 3 -b 5 -b 7 {img_path} {out_img}"
    #os.system("gdal_translate -of GTiff -co TILED=YES -co BIGTIFF=YES -co COMPRESS=LZW \"" + in_file + "\" \"" + cog_file + "\"")
    os.system(gdal_translate_cmd)
    print(f"Output image: {out_img}")
