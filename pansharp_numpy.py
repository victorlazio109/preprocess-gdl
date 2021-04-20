import numpy as np
import rasterio
import argparse
import os
import gc
import pandas as pd
import cv2
from datetime import datetime
from pathlib import Path
from rasterio.io import MemoryFile
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.cogeo import cog_validate
from rio_cogeo.profiles import cog_profiles

time_frame = datetime.now().strftime("%Y-%m-%d_%I-%M-%S_%p")
print(time_frame)


# Create Cogs
def mem_cog(raster, meta, filename):
    config = dict(
        GDAL_NUM_THREADS="ALL_CPUS",
        GDAL_TIFF_INTERNAL_MASK=False,
        GDAL_TIFF_OVR_BLOCKSIZE="128",

    )
    with MemoryFile() as memfile:
        with memfile.open(**meta) as mem:
            # Populate the input file with numpy array
            mem.write(raster)
            dst_profile = cog_profiles.get("deflate")
            dst_profile.update(dict(BIGTIFF="IF_SAFER"))
            cog_translate(
                mem,
                filename,
                dst_profile,
                nodata=0,
                add_mask=False,
                config=config,
                in_memory=True,
                quiet=True)

    if cog_validate(filename):
        print('COGs created and validated')
        with open('cog_list_' + time_frame + '.txt', 'a') as f:
            print(f"{filename}", file=f)


def write_array(out_path, raster, meta):
    with rasterio.open(out_path, 'w+', **meta) as dest:
        dest.write(raster)


# Normalize bands into 0.0 - 1.0 scale
def normalize(array):
    array_min = array.min()
    array_max = array.max()
    array -= array_min
    array /= array_max - array_min
    return array.astype(np.float32)


def pansharpen(m, pan, method='brovey', w=0.2):
    """
    Code adapted from: https://www.kaggle.com/resolut/panchromatic-sharpening
    """

    with rasterio.open(m) as f:
        metadata_ms = f.profile
        img_ms = np.moveaxis(f.read().astype(np.float32), 0, -1)
        for band in range(img_ms.shape[2]):
            img_ms[:, :, band] = normalize(img_ms[:, :, band])

        print('m_shape:', img_ms.shape)

    with rasterio.open(pan) as g:
        metadata_pan = g.profile
        img_pan = normalize(g.read(1).astype(np.float32))
        print('pan_shape:', img_pan.shape)

    ms_to_pan_ratio = metadata_ms['transform'][0] / metadata_pan['transform'][0]

    if ms_to_pan_ratio == 1:
        ms_to_pan_ratio = 4

    rescaled_ms = cv2.resize(img_ms, dsize=None, fx=ms_to_pan_ratio, fy=ms_to_pan_ratio,
                             interpolation=cv2.INTER_LINEAR).astype(np.float32)

    if img_pan.shape[0] < rescaled_ms.shape[0]:
        ms_row_bigger = True
        rescaled_ms = rescaled_ms[: img_pan.shape[0], :, :]
    else:
        ms_row_bigger = False
        img_pan = img_pan[: rescaled_ms.shape[0], :]

    if img_pan.shape[1] < rescaled_ms.shape[1]:
        ms_column_bigger = True
        rescaled_ms = rescaled_ms[:, : img_pan.shape[1], :]
    else:
        ms_column_bigger = False
        img_pan = img_pan[:, : rescaled_ms.shape[1]]

    if ms_row_bigger == True and ms_column_bigger == True:
        img_psh = np.empty((img_pan.shape[0], img_pan.shape[1], rescaled_ms.shape[2]), dtype=np.float32)
    elif ms_row_bigger == False and ms_column_bigger == True:
        img_psh = np.empty((rescaled_ms.shape[0], img_pan.shape[1], rescaled_ms.shape[2]), dtype=np.float32)
        metadata_pan['height'] = rescaled_ms.shape[0]
    elif ms_row_bigger == True and ms_column_bigger == False:
        img_psh = np.empty((img_pan.shape[0], rescaled_ms.shape[1], rescaled_ms.shape[2]), dtype=np.float32)
        metadata_pan['width'] = rescaled_ms.shape[1]
    else:
        img_psh = np.empty((rescaled_ms.shape), dtype=np.float32)
        metadata_pan['height'] = rescaled_ms.shape[0]
        metadata_pan['width'] = rescaled_ms.shape[1]

    del img_ms
    gc.collect()

    if method == 'simple_brovey':
        all_in = rescaled_ms[:, :, 0] + rescaled_ms[:, :, 1] + rescaled_ms[:, :, 2] + rescaled_ms[:, :, 3]
        for band in range(rescaled_ms.shape[2]):
            img_psh[:, :, band] = np.multiply(rescaled_ms[:, :, band], (img_pan / all_in))

    if method == 'simple_mean':
        for band in range(rescaled_ms.shape[2]):
            img_psh[:, :, band] = 0.5 * (rescaled_ms[:, :, band] + img_pan)

    if method == 'esri':
        ADJ = img_pan - rescaled_ms.mean(axis=2)
        for band in range(rescaled_ms.shape[2]):
            img_psh[:, :, band] = rescaled_ms[:, :, band] + ADJ

    if method == 'brovey':
        DNF = (img_pan - w * rescaled_ms[:, :, 3]) / (
                w * rescaled_ms[:, :, 0] + w * rescaled_ms[:, :, 1] + w * rescaled_ms[:, :, 2])
        for band in range(rescaled_ms.shape[2]):
            img_psh[:, :, band] = rescaled_ms[:, :, band] * DNF

    if method == 'hsv':
        img_psh = cv2.cvtColor(rescaled_ms[:, :, :3], cv2.COLOR_RGB2HSV).astype(np.float32)
        img_psh[:, :, 2] = img_pan - rescaled_ms[:, :, 3]
        img_psh = cv2.cvtColor(img_psh, cv2.COLOR_HSV2RGB).astype(np.float32)

    del img_pan, rescaled_ms
    gc.collect()
    return img_psh


def main(basedir, method="simple_mean", weight=0.1):

    # if basedir.is_file():
    #     df = pd.read_csv(basedir, sep=';', usecols=[0, 1], names=['MUL', 'PAN'])
    #     for x, y in df.items():
    #         print(type(x))
    #         print(y)

    # Gather files in list
    mul_pattern = os.path.join('**', '*_MUL', '*P00?.')
    exts = ['TIF', 'NTF']
    mul_tif_pattern = [f for ext in exts for f in sorted(basedir.glob(mul_pattern + ext))]

    def filename_generator():
        for mul_tif in mul_tif_pattern:
            mul_tif_splits = mul_tif.stem.split('-M')
            glob_regex = '%s_PAN\%s*%s%s' % (f"{mul_tif.parent.stem}".split("_MUL")[0],
                                             mul_tif_splits[0][:-1],
                                             mul_tif_splits[-1][4:],
                                             mul_tif.suffix)
            pan_file = sorted(mul_tif.parent.parent.glob(glob_regex))
            if len(pan_file) != 0:
                yield (f"{mul_tif}"), (f"{pan_file[0]}")

    # Pansharp Images and Cog
    for img_s in filename_generator():
        m_tif, p_tif = img_s

        with rasterio.open(m_tif) as m:
            ms_meta = m.meta
            if ms_meta['count'] > 4:
                with open('skipped_imgs_' + time_frame + '.txt', 'a') as f:
                    print(m_tif, file=f)
                continue

        with rasterio.open(p_tif, 'r') as pan:
            out_meta = pan.meta
            if out_meta['height'] + out_meta['width'] > 40000:
                with open('skipped_imgs' + time_frame + '.txt', 'a') as f:
                    print(p_tif, file=f)
                continue
        psh_img = pansharpen(m_tif, p_tif, method=method, w=weight)

        psh_img = psh_img * 255

        psh_img = psh_img.astype(np.uint8)

        psh_img = np.moveaxis(psh_img, -1, 0)
        print('psh_shape', psh_img.shape)

        output_path = Path(m_tif).parent.parent / (Path(m_tif).parent.stem[:-4] + '_PREP') / 'COG'
        output_path.mkdir(parents=True, exist_ok=True)
        m_tif = Path(m_tif)
        mul_tif_splits = m_tif.stem.split('-M')
        output_psh_name = (mul_tif_splits[0] + ('_PSH_%s_' % (method)) + mul_tif_splits[
            -1] + "_" + "uint8" + ".TIF")
        output_cog_abs_path = output_path / output_psh_name
        with open('out_abs_path_' + time_frame + '.txt', 'a') as f:
            print(output_cog_abs_path, file=f)

        if os.path.isfile(output_cog_abs_path):
            os.remove(output_cog_abs_path)

        out_meta.update({"driver": "GTiff",
                         "height": psh_img.shape[1],
                         "width": psh_img.shape[2],
                         "count": psh_img.shape[0],
                         "dtype": 'uint8'})
        mem_cog(psh_img, out_meta, output_cog_abs_path)
        # write_array(output_cog_abs_path, psh_img, out_meta)
        psh_img = None
        out_meta = None
        del psh_img, out_meta


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='PanSharp Script')
    parser.add_argument('path', type=str, help="path containing MUL & PAN dirs or CSV file")
    parser.add_argument('method', type=str,
                        choices=['simple_brovey', 'brovey', 'simple_mean', 'esri', 'hsv'],
                        help="pansharp algorithms")
    parser.add_argument('--weight', type=float, default=0.1, help=" weight value [0-1]")
    args = parser.parse_args()
    basedir = Path(args.path)

    main(basedir,
         method=args.method,
         weight=args.weight)
    gc.collect()

