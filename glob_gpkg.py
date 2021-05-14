import glob
import csv

def main():
    findgpkg = glob.glob('/wshare/travail/bdgrid2/EXTRACTION/Deep_learning/GDL_EAU_2019_20/geopackage/4_inventaire/*.gpkg', recursive=True)
    print(len(findgpkg))
    with open('inventaire.csv', 'w', newline='') as file:
        writer = csv.writer(file)
        for i in findgpkg:
            writer.writerow([i])

if __name__ == '__main__':
    main()