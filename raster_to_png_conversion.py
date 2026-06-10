import os
import rasterio
from rasterio.warp import transform_bounds
import numpy as np
import matplotlib
# Forces matplotlib to work in the background without opening UI windows
matplotlib.use('Agg') 
import matplotlib.pyplot as plt

def generate_overlay(tif_path, png_path, colormap='viridis', fallback_bounds=None):
    """
    Converts a GeoTIFF to an RGBA PNG overlay. Uses fallback_bounds if CRS is missing.
    """
    print(f"Processing {tif_path}...")
    
    with rasterio.open(tif_path) as src:
        # 1. Handle Missing CRS Metadata gracefully
        try:
            left, bottom, right, top = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
            pydeck_bounds = [left, bottom, right, top]
        except Exception as e:
            if fallback_bounds:
                print(f"  ⚠️ Warning: CRS missing in {tif_path}. Applying fallback bounds.")
                pydeck_bounds = fallback_bounds
            else:
                raise ValueError(f"Cannot process {tif_path} without a valid CRS and no fallback bounds available.")
        
        # 2. Read the first band
        band1 = src.read(1)
        nodata = src.nodata
        
        # 3. Mask out NoData values and NaNs
        if nodata is not None:
            mask = (band1 == nodata) | np.isnan(band1)
        else:
            mask = np.isnan(band1)
            
        data_masked = np.ma.masked_array(band1, mask=mask)
        
        # 4. Normalize the data between 0 and 1
        vmin, vmax = data_masked.min(), data_masked.max()
        normalized_data = (data_masked - vmin) / (vmax - vmin)
        
        # 5. Apply the Matplotlib colormap
        cmap = plt.get_cmap(colormap)
        rgba_image = cmap(normalized_data)
        
        # 6. Apply full transparency to NoData pixels
        rgba_image[mask, 3] = 0.0
        
        # 7. Save the resulting array as a PNG
        plt.imsave(png_path, rgba_image)
        
        print(f"  ✅ Saved to {png_path}")
        return pydeck_bounds

# --- Batch Processing ---
if __name__ == "__main__":
    data_dir = "./data/" 
    output_dir = "./outputs/"
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    targets = {
        "Uranium": {"tif": f"{data_dir}CO_MID_u.tif", "png": f"{output_dir}u_baseline.png", "cmap": "plasma"},
        "Thorium": {"tif": f"{data_dir}CO_MID_th.tif", "png": f"{output_dir}th_baseline.png", "cmap": "inferno"},
        "Potassium": {"tif": f"{data_dir}CO_MID_k.tif", "png": f"{output_dir}k_baseline.png", "cmap": "viridis"},
        "RTP_Mag": {"tif": f"{data_dir}CO_MID_rtp.tif", "png": f"{output_dir}rtp_mag_baseline.png", "cmap": "cividis"}
    }
    
    bounds_dictionary = {}
    master_bounds = None # Store the successful bounds here
    
    for layer, config in targets.items():
        if os.path.exists(config["tif"]):
            bounds = generate_overlay(
                tif_path=config["tif"], 
                png_path=config["png"], 
                colormap=config["cmap"],
                fallback_bounds=master_bounds
            )
            bounds_dictionary[layer] = bounds
            
            # Save the bounds from the first successful run (likely Uranium) to use as a fallback
            if master_bounds is None:
                master_bounds = bounds
        else:
            print(f"⚠️ File not found: {config['tif']}")
            
    print("\n--- Final RASTER_BOUNDS for dashboard.py ---")
    # Since they are all from the same survey grid, you only need one bounds array for Streamlit!
    if master_bounds:
        print(f"RASTER_BOUNDS = {master_bounds}")