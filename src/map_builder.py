import pydeck as pdk

def generate_map_layers(selected_layer_label, hd_run_map, raster_run_map, master_geojson):
    layers = []

    if selected_layer_label in hd_run_map:
        target_size, target_epsilon = hd_run_map[selected_layer_label]
        filtered_features = [
            f for f in master_geojson['features']
            if f['properties']['min_cluster_size'] == target_size
            and f['properties']['epsilon'] == target_epsilon
        ]
        filtered_geojson = {"type": "FeatureCollection", "features": filtered_features}
        
        layers.append(pdk.Layer(
            "GeoJsonLayer",
            data=filtered_geojson,
            opacity=0.65, 
            stroked=True,
            filled=True,
            extruded=True,  
            wireframe=True, 
            get_fill_color="properties.fill_color",
            get_line_color=[200, 200, 200, 120], 
            get_line_width=30, 
            line_width_min_pixels=1,
            get_elevation="properties.mean_U_ppm",
            elevation_scale=50, 
            pickable=True,
            auto_highlight=True 
        ))
        return layers, len(filtered_features), "vector"

    elif selected_layer_label in raster_run_map:
        raster_data = raster_run_map[selected_layer_label]
        url =  raster_data.get('image_url')
        bounds = raster_data.get('bounds')
        
        if url and bounds:
            layers.append(pdk.Layer(
                "BitmapLayer",
                id="active_raster_overlay", 
                image=url, 
                bounds=bounds,
                opacity=0.75,
                pickable=False
            ))
            return layers, 1, "raster"
            
    return layers, 0, "none"
