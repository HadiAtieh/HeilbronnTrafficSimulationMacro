# map_select_and_simulate.py
import osmnx as ox
import folium
from shapely.geometry import LineString
from uxsim import World
import random

# ================================================================
# PART 1 — DRAW MAP (CORRECTLY BOUNDED AROUND HEILBRONN)
# ================================================================

def draw_network_map(G, file_name):
    # Convert to WGS84 so Folium works correctly
    G_latlon = ox.project_graph(G, to_crs="EPSG:4326")

    # Compute bounding box only around Heilbronn graph
    nodes = list(G_latlon.nodes(data=True))
    lats = [d['y'] for (_, d) in nodes]
    lons = [d['x'] for (_, d) in nodes]

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2

    # Create map inside bounding box
    m = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="OpenStreetMap")

    # Draw only edges inside bounding box
    for u, v, data in G_latlon.edges(data=True):
        if "geometry" in data:
            coords = data["geometry"].coords
        else:
            coords = [
                (G_latlon.nodes[u]['x'], G_latlon.nodes[u]['y']),
                (G_latlon.nodes[v]['x'], G_latlon.nodes[v]['y'])
            ]

        folium.PolyLine(
            [(lat, lon) for lon, lat in coords],  # convert lon/lat → lat/lon
            weight=3,
            color="blue",
            opacity=0.8
        ).add_to(m)

    m.save(file_name)
    print(f"Map saved → {file_name}")


# ================================================================
# PART 2 — EXPORT ROADS AND LET USER REMOVE BY NAME
# ================================================================

def export_roads_to_text(G, file_name="roads.txt"):
    edges = list(G.edges(data=True))
    with open(file_name, "w") as f:
        for u, v, d in edges:
            name = d.get("name", "Unnamed")
            f.write(f"{name} | from {u} → {v}\n")
    print(f"Road list exported → {file_name}")

def remove_roads_by_name(G):
    # Ask how many streets the user wants to remove
    try:
        n = int(input("\nHow many streets do you want to close? "))
    except:
        print("Invalid input. Using 1 street.")
        n = 1

    streets_to_remove = []
    for i in range(n):
        street_name = input(f"Enter the NAME of street {i+1}: ").strip()
        streets_to_remove.append(street_name)

    # Collect edges to remove
    edges_to_remove = []
    for target in streets_to_remove:
        for u, v, d in G.edges(data=True):
            name = d.get("name", "Unnamed")
            if isinstance(name, list):
                match = any(target.lower() in n.lower() for n in name)
            else:
                match = target.lower() in name.lower()

            if match:
                edges_to_remove.append((u, v))

    # Remove edges
    if not edges_to_remove:
        print("⚠ No matching roads found.")
        return

    print("\nRemoving the following edges:")
    for u, v in edges_to_remove:
        print(f" - {u} → {v}")
        if G.has_edge(u, v):
            G.remove_edge(u, v)

# ================================================================
# HELPER — generate OD pairs from user-specified streets
# ================================================================

def get_user_defined_od(G):
    """
    Returns a list of (origin_node, destination_node) pairs
    based on user input of street names.
    """
    edges_by_name = {}
    for u, v, data in G.edges(data=True):
        name = data.get("name", "Unnamed")
        if isinstance(name, list):
            for n in name:
                edges_by_name.setdefault(n.lower(), []).append((u, v))
        else:
            edges_by_name.setdefault(name.lower(), []).append((u, v))

    od_pairs = []
    try:
        n_pairs = int(input("How many OD pairs to generate? "))
    except:
        n_pairs = 1

    for i in range(n_pairs):
        origin_street = input(f"Enter origin street name for pair {i+1}: ").strip().lower()
        dest_street   = input(f"Enter destination street name for pair {i+1}: ").strip().lower()

        if origin_street not in edges_by_name:
            print(f"⚠ No edges found for {origin_street}, skipping this pair.")
            continue
        if dest_street not in edges_by_name:
            print(f"⚠ No edges found for {dest_street}, skipping this pair.")
            continue

        # Pick random nodes along the chosen street edges
        origin_edge = random.choice(edges_by_name[origin_street])
        dest_edge   = random.choice(edges_by_name[dest_street])

        od_pairs.append((origin_edge[0], dest_edge[1]))

    return od_pairs


# ================================================================
# PART 3 — BUILD UXSIM WORLD
# ================================================================

def build_world_from_graph(G, name):
    W = World(
        name=name,
        deltan=5,
        tmax=1800,
        print_mode=1,
        save_mode=0,
        show_mode=0,
    )

    node_map = {nid: W.addNode(f"n{nid}", data["x"], data["y"])
                for nid, data in G.nodes(data=True)}

    for idx, (u, v, data) in enumerate(G.edges(data=True)):
        length = data.get("length", 100)
        maxspeed = data.get("maxspeed", 13.9)

        if isinstance(maxspeed, list):
            maxspeed = float(maxspeed[0])
        elif isinstance(maxspeed, str):
            try:
                maxspeed = float(maxspeed.split()[0])
            except:
                maxspeed = 13.9

        W.addLink(
            f"l{u}_{v}_{idx}",
            node_map[u],
            node_map[v],
            length=length,
            free_flow_speed=maxspeed,
            jam_density=0.2,
        )

    # Ask user for OD pairs
    od_pairs = get_user_defined_od(G)

    if not od_pairs:
        # Fallback: random OD pairs (old behavior)
        print("No valid OD pairs provided. Generating random OD pairs.")
        ys = [data["y"] for _, data in G.nodes(data=True)]
        north = [n for n, d in G.nodes(data=True) if d["y"] > max(ys) - 2000]
        south = [n for n, d in G.nodes(data=True) if d["y"] < min(ys) + 2000]
        for _ in range(40):
            od_pairs.append((random.choice(north), random.choice(south)))

    # Add demands
    for origin, dest in od_pairs:
        W.adddemand(node_map[origin], node_map[dest], 0, 1800, 0.03)

    return W



# ================================================================
# MAIN PROGRAM
# ================================================================

print("Downloading Heilbronn OSM data...")
G = ox.graph_from_place("Heilbronn, Germany", network_type="drive")
G = ox.project_graph(G)  # project to UTM for UXsim

# Export road names for user
export_roads_to_text(G, "roads.txt")

# Draw map BEFORE closure
draw_network_map(G, "heilbronn_before.html")

# Ask user which road to remove
remove_roads_by_name(G)

# Draw map AFTER closure
draw_network_map(G, "heilbronn_after.html")


# Baseline simulation
print("\nRunning baseline simulation...")
W_before = build_world_from_graph(G, "before")
W_before.exec_simulation()

print("\nBASELINE STATISTICS:")
W_before.analyzer.print_simple_stats()

# After-closure simulation
print("\nRunning simulation after closure...")
W_after = build_world_from_graph(G, "after")
W_after.exec_simulation()

print("\nAFTER CLOSURE STATISTICS:")
W_after.analyzer.print_simple_stats()

# Comparison
print("\n========= COMPARISON =========")
before_delay = W_before.analyzer.delay_total
after_delay = W_after.analyzer.delay_total

print(f"Delay BEFORE: {before_delay:.2f}")
print(f"Delay AFTER : {after_delay:.2f}")
print(f"Difference  : {after_delay - before_delay:.2f}")

if after_delay > before_delay:
    print("🔥 Traffic got WORSE after closure.")
else:
    print("✅ Traffic did NOT worsen overall.")
