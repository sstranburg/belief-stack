import json
import numpy as np
from datetime import datetime
import textwrap


def load_actor_storms(path="data/derived/actor_storms.jsonl"):
    """Load actor storms from JSONL."""
    storms = []
    with open(path, 'r') as f:
        for line in f:
            data = json.loads(line)
            storms.append({
                'storm_id': data['storm_id'],
                'actor': data['actor'],
                'start_ts': data['created_at'],
                'end_ts': data['updated_at'],
                'event_count': data['event_count'],
                'event_ids': data['event_ids'],
                'centroid': None,  # Will be computed from events
                'representative_titles': [e['title'] for e in data.get('representative_events', [])]
            })
    return storms


def load_storm_trajectories(path="data/derived/storm_trajectories.jsonl"):
    """Load storm trajectories from JSONL."""
    trajectories = []
    with open(path, 'r') as f:
        for line in f:
            data = json.loads(line)
            trajectories.append({
                'trajectory_id': data['trajectory_id'],
                'actor': data['actor'],
                'window_count': data['window_count'],
                'total_events': data['total_events'],
                'state': data.get('state', 'stable'),
                'latest_density': data.get('latest_density', 0),
                'latest_momentum': data.get('latest_momentum', 0),
                'latest_drift': data.get('latest_drift', 0),
                'metrics': data['metrics']
            })
    return trajectories


def load_events(path="data/normalized/tech_ecosystem.jsonl"):
    """Load normalized events from JSONL."""
    events = []
    with open(path, 'r') as f:
        for line in f:
            data = json.loads(line)
            events.append({
                'event_id': data['event_id'],
                'timestamp': data['timestamp'],
                'actors': data['actors'],
                'title': data['title'],
                'text': data['text']
            })
    return events


def load_embeddings(path="data/derived/tech_ecosystem_embeddings.npz"):
    """Load embeddings and create event_id lookup."""
    data = np.load(path)
    embeddings = data['embeddings']
    event_ids = data['event_ids']
    
    # Create lookup dictionary
    embedding_lookup = {
        str(event_id): embeddings[i]
        for i, event_id in enumerate(event_ids)
    }
    
    return embedding_lookup, embeddings


def test_loaders():
    """Test all data loaders."""
    print("Testing data loaders...\n")
    
    storms = load_actor_storms()
    print(f"✓ Loaded {len(storms)} actor storms")
    
    trajectories = load_storm_trajectories()
    print(f"✓ Loaded {len(trajectories)} trajectories")
    
    events = load_events()
    print(f"✓ Loaded {len(events)} events")
    
    embedding_lookup, embeddings = load_embeddings()
    print(f"✓ Loaded embeddings: shape {embeddings.shape}")
    print(f"✓ Embedding lookup has {len(embedding_lookup)} entries")
    
    return storms, trajectories, events, embedding_lookup, embeddings


if __name__ == "__main__":
    test_loaders()


from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.dates import date2num
import matplotlib.dates as mdates
from scipy.ndimage import gaussian_filter
from scipy.stats import gaussian_kde


def compute_storm_centroids(storms, events, embedding_lookup):
    """Compute centroid for each storm from its member events."""
    event_lookup = {e['event_id']: e for e in events}
    
    for storm in storms:
        event_embeddings = []
        for event_id in storm['event_ids']:
            if event_id in embedding_lookup:
                event_embeddings.append(embedding_lookup[event_id])
        
        if event_embeddings:
            storm['centroid'] = np.mean(event_embeddings, axis=0)
        else:
            storm['centroid'] = None
    
    return storms


def project_to_2d(storms, events, embedding_lookup):
    """Project storm centroids and event embeddings to 2-D using PCA."""
    # Collect all storm centroids
    centroids = []
    valid_storms = []
    for storm in storms:
        if storm['centroid'] is not None:
            centroids.append(storm['centroid'])
            valid_storms.append(storm)
    
    if not centroids:
        return storms, events
    
    centroids = np.array(centroids)
    
    # Fit PCA with 2 components
    pca = PCA(n_components=2)
    pca.fit(centroids)
    
    # Project storm centroids
    for storm in valid_storms:
        projection = pca.transform([storm['centroid']])[0]
        storm['semantic_y'] = float(projection[0])  # PC1 for y-axis
        storm['semantic_c'] = float(projection[1])  # PC2 for color
    
    # Project event embeddings
    for event in events:
        if event['event_id'] in embedding_lookup:
            emb = embedding_lookup[event['event_id']]
            projection = pca.transform([emb])[0]
            event['semantic_y'] = float(projection[0])  # PC1 for y-axis
            event['semantic_c'] = float(projection[1])  # PC2 for color
        else:
            event['semantic_y'] = None
            event['semantic_c'] = None
    
    print(f"\n✓ PCA explained variance: PC1={pca.explained_variance_ratio_[0]:.3f}, PC2={pca.explained_variance_ratio_[1]:.3f}")
    
    return storms, events


def assign_time_positions(storms, events):
    """Assign x-axis (time) coordinates."""
    for storm in storms:
        start = datetime.fromisoformat(storm['start_ts'].rstrip('Z'))
        end = datetime.fromisoformat(storm['end_ts'].rstrip('Z'))
        mid = start + (end - start) / 2
        storm['time_x'] = date2num(mid)
        storm['duration_days'] = (end - start).days
    
    for event in events:
        ts = datetime.fromisoformat(event['timestamp'].rstrip('Z'))
        event['time_x'] = date2num(ts)
    
    return storms, events


def assign_events_to_storms(storms, events):
    """Map events to their storms."""
    event_lookup = {e['event_id']: e for e in events}
    
    for storm in storms:
        storm['events'] = []
        for event_id in storm['event_ids']:
            if event_id in event_lookup:
                event = event_lookup[event_id]
                if event.get('semantic_y') is not None and event.get('time_x') is not None:
                    storm['events'].append(event)
    
    return storms


def compute_density_field(storms, grid_x=250, grid_y=180, gaussian_sigma=1.6):
    """Compute 2D density field over time × semantic_y space using histogram + Gaussian smoothing."""
    # Collect all event coordinates
    all_x = []
    all_y = []
    
    for storm in storms:
        for event in storm.get('events', []):
            if event.get('time_x') is not None and event.get('semantic_y') is not None:
                all_x.append(event['time_x'])
                all_y.append(event['semantic_y'])
    
    if not all_x:
        return None, None, None, 0
    
    all_x = np.array(all_x)
    all_y = np.array(all_y)
    
    # Define grid bounds
    x_min, x_max = all_x.min(), all_x.max()
    y_min, y_max = all_y.min(), all_y.max()
    
    # Add padding
    x_range = x_max - x_min
    y_range = y_max - y_min
    x_min -= x_range * 0.05
    x_max += x_range * 0.05
    y_min -= y_range * 0.05
    y_max += y_range * 0.05
    
    # Create 2D histogram
    density, x_edges, y_edges = np.histogram2d(
        all_x, all_y,
        bins=[grid_x, grid_y],
        range=[[x_min, x_max], [y_min, y_max]]
    )
    
    # Apply Gaussian smoothing
    density_smooth = gaussian_filter(density, sigma=gaussian_sigma)
    
    # Create grid for plotting
    x_grid = (x_edges[:-1] + x_edges[1:]) / 2
    y_grid = (y_edges[:-1] + y_edges[1:]) / 2
    
    return density_smooth, x_grid, y_grid, len(all_x)


def plot_storm_field(storms, trajectories, output_path="data/derived/storm_field_real_data.png", 
                     filter_actors=None, use_2d_semantic=False, show_density=False,
                     density_alpha=0.22, density_contours=6, grid_x=250, grid_y=180, gaussian_sigma=1.6,
                     show_state=False):
    """Create complete storm field visualization with optional density background and state encoding."""
    fig, ax = plt.subplots(figsize=(16, 10))
    
    # Filter storms if requested
    if filter_actors:
        storms = [s for s in storms if s['actor'] in filter_actors]
        trajectories = [t for t in trajectories if t['actor'] in filter_actors]
    
    # State visual encoding
    state_styles = {
        'emerging': {'linestyle': '--', 'linewidth': 2},
        'growing': {'linestyle': '-', 'linewidth': 3},
        'peaking': {'linestyle': '-', 'linewidth': 4},
        'fading': {'linestyle': ':', 'linewidth': 2},
        'stable': {'linestyle': '-', 'linewidth': 1},
        'volatile': {'linestyle': '-.', 'linewidth': 2}
    }
    
    # Map trajectory states to storms by actor
    storm_states = {}
    if show_state:
        for traj in trajectories:
            actor = traj.get('actor', '')
            state = traj.get('state', 'stable')
            # Assign state to all storms of this actor
            for storm in storms:
                if storm['actor'] == actor:
                    storm_states[storm['storm_id']] = state
    
    # Get semantic_c range for color normalization
    if use_2d_semantic:
        all_semantic_c = [s['semantic_c'] for s in storms if s.get('semantic_c') is not None]
        all_semantic_c.extend([e['semantic_c'] for s in storms for e in s.get('events', []) 
                              if e.get('semantic_c') is not None])
        if all_semantic_c:
            vmin, vmax = min(all_semantic_c), max(all_semantic_c)
            cmap = plt.cm.coolwarm
            norm = plt.Normalize(vmin=vmin, vmax=vmax)
        else:
            use_2d_semantic = False
    
    # Color map for actors (fallback if not using 2D semantic)
    actors = sorted(set(s['actor'] for s in storms))
    colors = plt.cm.tab10(np.linspace(0, 1, len(actors)))
    actor_colors = {actor: colors[i] for i, actor in enumerate(actors)}
    
    # Compute and plot density field if requested
    density_event_count = 0
    if show_density:
        density_smooth, x_grid, y_grid, density_event_count = compute_density_field(
            storms, grid_x=grid_x, grid_y=grid_y, gaussian_sigma=gaussian_sigma
        )
        
        if density_smooth is not None:
            # Plot density as background heatmap
            X, Y = np.meshgrid(x_grid, y_grid)
            im = ax.imshow(density_smooth.T, origin='lower', 
                          extent=[x_grid[0], x_grid[-1], y_grid[0], y_grid[-1]],
                          cmap='Greys', alpha=density_alpha, aspect='auto', zorder=0)
            
            # Add subtle contour lines
            if density_contours > 0:
                levels = np.linspace(density_smooth.min(), density_smooth.max(), density_contours + 2)[1:-1]
                ax.contour(X, Y, density_smooth.T, levels=levels, 
                          colors='gray', linewidths=0.5, alpha=0.3, zorder=0)
    
    # Plot events as small points
    event_count = 0
    for storm in storms:
        if 'events' not in storm or not storm['events']:
            continue
        
        for event in storm['events']:
            if use_2d_semantic and event.get('semantic_c') is not None:
                color = cmap(norm(event['semantic_c']))
            else:
                color = actor_colors[storm['actor']]
            
            ax.scatter(event['time_x'], event['semantic_y'], 
                      s=10, alpha=0.3, color=color, zorder=1)
            event_count += 1
    
    # Draw storm regions as ellipses
    labeled_storms = []
    for storm in storms:
        if storm.get('semantic_y') is None:
            continue
        
        if use_2d_semantic and storm.get('semantic_c') is not None:
            color = cmap(norm(storm['semantic_c']))
        else:
            color = actor_colors[storm['actor']]
        
        # Get state style if available
        state = storm_states.get(storm['storm_id'], 'stable') if show_state else 'stable'
        style = state_styles.get(state, state_styles['stable'])
        
        # Ellipse dimensions
        width = max(storm['duration_days'] * 0.8, 0.5)
        
        if storm['events']:
            y_values = [e['semantic_y'] for e in storm['events']]
            height = max(np.std(y_values) * 4, 0.5)
        else:
            height = 0.5
        
        ellipse = patches.Ellipse(
            (storm['time_x'], storm['semantic_y']),
            width=width, height=height,
            fill=True, facecolor=color, edgecolor=color, 
            linewidth=style['linewidth'], linestyle=style['linestyle'],
            alpha=0.2, zorder=2
        )
        ax.add_patch(ellipse)
        
        # Track for labeling
        labeled_storms.append((storm, state, height, color))
        
    # Add storm name labels
    for storm, state, height, color in labeled_storms:
        if storm['representative_titles']:
            title = storm['representative_titles'][0][:60]
            if len(storm['representative_titles'][0]) > 60:
                title += '...'
            title = textwrap.fill(title, width=20)
            
            label_y = storm['semantic_y'] + height/2 + 0.2
            ax.text(storm['time_x'], label_y, 
                   title,
                   fontsize=7, ha='center', va='bottom', 
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                            edgecolor=color, alpha=0.8),
                   zorder=4)
        
        # Add event count for large storms
        if storm['event_count'] >= 50:
            ax.text(storm['time_x'], storm['semantic_y'], 
                   f"{storm['event_count']}", 
                   fontsize=9, ha='center', va='center', 
                   fontweight='bold', color='black', zorder=5)
    
    # Add sparse state labels for largest/most recent storms
    if show_state and labeled_storms:
        sorted_storms = sorted(labeled_storms, key=lambda x: (x[0]['event_count'], x[0]['time_x']), reverse=True)
        
        for i, (storm, state, height, color) in enumerate(sorted_storms[:7]):
            if state != 'stable':
                state_label = f"{storm['actor']} — {state}"
                label_y = storm['semantic_y'] - height/2 - 0.3
                
                ax.text(storm['time_x'], label_y,
                       state_label,
                       fontsize=8, ha='center', va='top',
                       bbox=dict(boxstyle='round,pad=0.4', facecolor='lightyellow',
                                edgecolor=color, linewidth=1.5, alpha=0.9),
                       zorder=5, fontweight='bold')
    
    # Draw trajectories
    traj_count = 0
    for traj in trajectories:
        if traj['window_count'] < 2:
            continue
        
        # Use neutral color for trajectories to avoid clutter
        color = 'gray'
        
        x_coords = []
        y_coords = []
        
        for metric in traj['metrics']:
            for storm in storms:
                if storm['actor'] == traj['actor'] and storm.get('semantic_y') is not None:
                    storm_start = datetime.fromisoformat(storm['start_ts'].rstrip('Z'))
                    window_start = datetime.fromisoformat(metric['window_start'].rstrip('Z'))
                    window_end = datetime.fromisoformat(metric['window_end'].rstrip('Z'))
                    
                    if window_start <= storm_start < window_end:
                        x_coords.append(storm['time_x'])
                        y_coords.append(storm['semantic_y'])
                        break
        
        if len(x_coords) >= 2:
            ax.plot(x_coords, y_coords, color=color, linewidth=1.5, alpha=0.4, zorder=2)
            traj_count += 1
    
    # Add annotations for interesting storms
    annotated = 0
    for storm in sorted(storms, key=lambda s: s['event_count'], reverse=True)[:3]:
        if storm.get('semantic_y') is not None and annotated < 3:
            ax.annotate(f"Density: {storm['event_count']}", 
                       xy=(storm['time_x'], storm['semantic_y']),
                       xytext=(10, 10), textcoords='offset points',
                       fontsize=9, bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                       arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
            annotated += 1
    
    # Formatting
    ax.set_xlabel('Time', fontsize=12)
    if use_2d_semantic:
        ax.set_ylabel('Semantic Position (Dimension 1)', fontsize=12)
        ax.set_title('Storm Field: Events, Situations, and Trajectories\n(Time × Semantic Dim 1, Colored by Semantic Dim 2)', 
                    fontsize=14, fontweight='bold')
    else:
        ax.set_ylabel('Semantic Position (1-D PCA Projection)', fontsize=12)
        ax.set_title('Storm Field: Events, Situations, and Trajectories', fontsize=14, fontweight='bold')
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    plt.xticks(rotation=45, ha='right')
    
    # Add colorbar for 2D semantic
    if use_2d_semantic:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, pad=0.02)
        cbar.set_label('Semantic Position (Dimension 2)', fontsize=11)
        
        # Add semantic theme labels
        cbar.ax.text(1.5, 0.05, 'Technical\nThemes', transform=cbar.ax.transAxes,
                    fontsize=9, va='bottom', ha='left', color='blue', fontweight='bold')
        cbar.ax.text(1.5, 0.95, 'Business/Market\nThemes', transform=cbar.ax.transAxes,
                    fontsize=9, va='top', ha='left', color='red', fontweight='bold')
    else:
        # Legend for actor colors
        legend_elements = [plt.Line2D([0], [0], marker='o', color='w', 
                                      markerfacecolor=actor_colors[actor], markersize=8, label=actor)
                          for actor in actors]
        ax.legend(handles=legend_elements, loc='upper left', fontsize=10)
    
    # Add state legend if showing states
    if show_state:
        legend_text = "State styles:\nemerging = dashed\ngrowing = thick solid\npeaking = bold solid\nfading = dotted\nstable = thin solid\nvolatile = dash-dot"
        ax.text(0.02, 0.98, legend_text, transform=ax.transAxes,
               fontsize=9, va='top', ha='left',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.8),
               family='monospace')
    
    # Clean up spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    # Count states if showing them
    state_counts = {}
    if show_state:
        for storm_id, state in storm_states.items():
            state_counts[state] = state_counts.get(state, 0) + 1
    
    if show_density:
        return event_count, len(storms), traj_count, density_event_count, state_counts
    return event_count, len(storms), traj_count, state_counts if show_state else {}
