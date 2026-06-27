# BGMI Erangel Zone Predictor

A Python desktop application built with Tkinter for annotating and predicting safe zones in Battlegrounds Mobile India (BGMI) specifically for the Erangel map.

The application allows users to draw flight paths and manually annotate the 8 phases of safe zones on the map. Using a built-in Machine Learning model, the app can predict future zone centers based on the flight path and previous zone data.

## Features

- **Interactive Map Canvas**: Pan, zoom, and interact with the Erangel map.
- **Flight Path & Zone Annotation**: Dedicated tools for drawing the flight path line and all 8 phases of the safe zone.
- **Machine Learning Predictor**: Uses `scikit-learn` (Gradient Boosting Regressor) to train on your saved matches and predict subsequent zone locations.
- **Geometric Heuristic Fallback**: If there are fewer than 5 matches saved, the app uses a smart mathematical fallback to estimate where zones will shift.
- **Analytics Dashboard**: View heatmaps of flight paths and zones, as well as model accuracy stats across all your annotated matches.
- **Dataset Manager**: All matches are saved as JSON files in a `dataset/` directory for easy access and sharing.
- **Export Capabilities**: Export the full dataset or training data to JSON, and export annotated matches as PNG images.

## Requirements

- Python 3.8+
- `scikit-learn` (for the machine learning model)
- `Pillow` (for exporting annotated maps to PNG)
- `tkinter` (Usually comes pre-installed with standard Python distributions)

You can install the dependencies via pip:
```bash
pip install scikit-learn Pillow
```

## How to Use

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Rohitt721/ZONE-PREDICTOR.git
   cd ZONE-PREDICTOR
   ```

2. **Run the Application**:
   ```bash
   python app.py
   ```
   *Note: On your first run, the app may ask you to locate your Erangel map image if it cannot find it in the default assets folder.*

3. **Annotate a Match**:
   - Use the **Flight Path Tool (P)** to draw the plane's route.
   - Use the **Circle Tool (C)** to draw the safe zones for phases 1 through 8.
   - Press **Ctrl + S** to save the match.

4. **Predict Zones**:
   - Once you have annotated the flight path (and optionally some early zones), click **Predict Zones** in the right panel.
   - The app will train on your saved matches and predict the rest!

## Project Structure

- `app.py`: Main application entry point and Tkinter window setup.
- `ui.py`, `map_canvas.py`, `annotation_tools.py`, `analytics_panel.py`: UI components and drawing logic.
- `predictor.py`: The machine learning core logic.
- `dataset_manager.py` & `storage.py`: Saves, loads, and manages match JSON files and configurations.
- `zone_manager.py`: Data models and constants for zone sizes and map specifications.
- `analytics.py`: Mathematical functions for the analytics heatmaps and stats.

## License
MIT License