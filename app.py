import streamlit as st
import simplekml
import math
import xml.etree.ElementTree as ET
from io import BytesIO
import os
import pandas as pd

# Konfigurasi halaman
st.set_page_config(page_title="Tiang Automation", page_icon="🌍", layout="wide")

# Fungsi haversine
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Parse KML LineString
def parse_linestrings_with_names(kml_content):
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    root = ET.fromstring(kml_content)
    linestrings = []
    for idx, placemark in enumerate(root.findall('.//kml:Placemark', ns)):
        name = placemark.find('kml:name', ns)
        line = placemark.find('.//kml:LineString', ns)
        if line is not None:
            coord_elem = line.find('kml:coordinates', ns)
            if coord_elem is not None and coord_elem.text:
                coord_pairs = coord_elem.text.strip().split()
                coords = []
                for pair in coord_pairs:
                    parts = pair.split(',')
                    if len(parts) >= 2:
                        lon, lat = map(float, parts[:2])
                        coords.append((lat, lon))
                label_name = name.text.strip() if name is not None else f"LineString_{idx+1}"
                linestrings.append({"name": label_name, "coords": coords, "index": idx})
    return linestrings

# Resample LineString
def resample_linestring(coords, interval):
    if len(coords) < 2:
        return []
    distances = []
    total_dist = 0
    for i in range(len(coords) - 1):
        d = haversine(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
        distances.append(d)
        total_dist += d
    num_points = int(total_dist // interval)
    result = []

    current_dist = 0
    i = 0
    seg_start = coords[0]
    seg_end = coords[1]
    seg_dist = distances[0]

    for n in range(num_points + 1):
        target_dist = n * interval
        while current_dist + seg_dist < target_dist and i < len(distances) - 1:
            current_dist += seg_dist
            i += 1
            seg_start = coords[i]
            seg_end = coords[i + 1]
            seg_dist = distances[i]
        remaining = target_dist - current_dist
        frac = remaining / seg_dist if seg_dist != 0 else 0
        lat = seg_start[0] + frac * (seg_end[0] - seg_start[0])
        lon = seg_start[1] + frac * (seg_end[1] - seg_start[1])
        result.append((lon, lat))

    if result[-1] != (coords[-1][1], coords[-1][0]):
        result.append((coords[-1][1], coords[-1][0]))

    return result

# Parse file tiang existing dari CSV
def parse_tiang_existing(file):
    df = pd.read_csv(file)
    tiang_data = []

    for _, row in df.iterrows():
        try:
            raw = row["wkt"].replace("POINT(", "").replace(")", "")
            lon, lat = map(float, raw.split())
            tiang_data.append({
                "name": row["name"],
                "description": row["designator"],
                "lat": lat,
                "lon": lon
            })
        except Exception:
            continue
    return tiang_data

# Buat file KML
def create_kml_with_folders(selected_lines, label_mapping, interval, tiang_data=None):
    kml = simplekml.Kml()
    folder_te = kml.newfolder(name="TE")
    folder_TN7 = kml.newfolder(name="TN7")
    folder_distribusi = kml.newfolder(name="DISTRIBUSI")
    
    icon_url = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"

    for line in selected_lines:
        label_type = label_mapping.get(line["index"])
        if label_type not in ["TE", "TN7"]:
            continue

        # Resample untuk distribusi
        resampled_coords = resample_linestring(line["coords"], interval)
        distrib_folder = folder_distribusi.newfolder(name=f"Distribusi {line['name']}")
        ls = distrib_folder.newlinestring(name=line['name'], coords=resampled_coords)
        ls.style.linestyle.width = 3
        ls.style.linestyle.color = simplekml.Color.blue

        point_folder = folder_te if label_type == "TE" else folder_TN7
        subfolder = point_folder.newfolder(name=line["name"])

        if label_type == "TE" and tiang_data:
            for tiang in tiang_data:
                pnt = subfolder.newpoint(
                    name=tiang["name"], 
                    coords=[(tiang["lon"], tiang["lat"])]
                )
                pnt.description = "PU-AS"  # fixed
                pnt.style.iconstyle.icon.href = icon_url
                pnt.style.iconstyle.scale = 1
                pnt.style.labelstyle.scale = 1
        elif label_type == "TN7":
            for lon, lat in resampled_coords:
                pnt = subfolder.newpoint(name="TN7", coords=[(lon, lat)])
                pnt.description = "PU-S7.0-400NM"  # fixed
                pnt.style.iconstyle.icon.href = icon_url
                pnt.style.iconstyle.scale = 1
                pnt.style.labelstyle.scale = 1

    return kml

# ========== Streamlit UI ==========

st.title("🌍 Auto KML Generator buat tiang semudah mengedipkan mata")
st.markdown("Unggah file KML dengan LineString, proses menjadi TE / TN7 / DISTRIBUSI. Jika punya data tiang existing, upload CSV untuk auto-label TE.")

with st.expander("⚙️ Upload & Pengaturan", expanded=True):
    uploaded_file = st.file_uploader("📂 Upload file KML", type=["kml"])
    tiang_file = st.file_uploader("📂 Upload file CSV Tiang Existing (opsional untuk TE)", type=["csv"])
    interval = st.number_input("📏 Jarak antar titik (meter)", min_value=1, value=100)

if uploaded_file:
    input_filename = os.path.splitext(uploaded_file.name)[0]
    kml_text = uploaded_file.read().decode('utf-8')
    lines = parse_linestrings_with_names(kml_text)

    st.markdown("## 🏷️ Pilih Label untuk Masing-masing LineString")
    label_map = {}
    for line in lines:
        col1, col2 = st.columns([3, 2])
        with col1:
            st.write(f"🔹 **{line['name']}**")
        with col2:
            choice = st.radio(f"Label untuk '{line['name']}'", ["Tidak dilabeli", "TE", "TN7"],
                              key=f"label_{line['index']}", horizontal=True)
            label_map[line["index"]] = choice

    if st.button("🚀 Gaskeun Buat KML nya"):
        tiang_data = None
        if tiang_file:
            try:
                tiang_data = parse_tiang_existing(tiang_file)
                st.success(f"✅ {len(tiang_data)} titik dari file tiang berhasil diproses.")
            except Exception as e:
                st.error(f"❌ Gagal membaca file tiang: {e}")

        with st.spinner("Membuat struktur KML..."):
            kml_result = create_kml_with_folders(lines, label_map, interval, tiang_data=tiang_data)
            kml_bytes = kml_result.kml().encode('utf-8')
            output_name = f"{input_filename}_jmsolution.kml"

            st.success(f"✅ File KML berhasil dibuat: `{output_name}`")
            st.download_button("⬇️ Download KML Nya boskuh", data=kml_bytes,
                               file_name=output_name,
                               mime="application/vnd.google-earth.kml+xml")

            st.subheader("🖼️ Ikon Label:")
            st.image("https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png", width=50)

st.markdown("---")
st.caption("© 2025 JM Solution | Telegram: @ferdianjm 🫶🏻 AI.")
