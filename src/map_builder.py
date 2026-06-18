import pydeck as pdk

def generate_map_layers(selected_vector, selected_raster, hd_run_map, raster_run_map, master_geojson, raster_opacity=0.6):
    layers = []
    feature_count = 0
    
    # 1. Build the Raster Layer FIRST (so it sits on the bottom)
    if selected_raster != "None":
        raster_data = raster_run_map[selected_raster]
        raster_url = raster_data['url']
        raster_bounds = raster_data['bounds']  # Ensure this matches PyDeck's expected format: [[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat]]
        
        raster_layer = pdk.Layer(
            "BitmapLayer",
            image=raster_url,
            bounds=raster_bounds,
            opacity=raster_opacity,
            pickable=False # Turn off picking for the raster so tooltips don't clash
        )
        layers.append(raster_layer)

    # 2. Build the Vector Layer SECOND (so it sits on top)
    if selected_vector != "None":
        target_size, target_eps = hd_run_map[selected_vector]
        
        # Filter the master GeoJSON for only the selected run
        filtered_features = [
            f for f in master_geojson['features'] 
            if f['properties'].get('min_cluster_size') == target_size and f['properties'].get('epsilon') == target_eps
        ]
        feature_count = len(filtered_features)
        
        vector_layer = pdk.Layer(
            "GeoJsonLayer",
            data={"type": "FeatureCollection", "features": filtered_features},
            opacity=0.8,
            stroked=True,
            filled=True,
            extruded=False,
            wireframe=True,
            get_fill_color="properties.fill_color",
            get_line_color=[255, 255, 255, 255],
            get_line_width=20, # Width in meters
            pickable=True
        )
        layers.append(vector_layer)

    # We removed 'layer_type' from the return statement since we can now have multiple types active
    return layers, feature_count
