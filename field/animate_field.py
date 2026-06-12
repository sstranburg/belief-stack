import json
import numpy as np
from datetime import datetime, timedelta
from sklearn.decomposition import PCA
from matplotlib.dates import date2num
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.dates as mdates
from scipy.ndimage import gaussian_filter
import imageio

WINDOW_DAYS = 7  # Shorter window for concentrated data
STEP_DAYS = 1  # Daily steps to show progression


def generate_animation_windows(events, window_days=WINDOW_DAYS, step_days=STEP_DAYS, start_date_override=None):
    """Generate rolling windows for animation, focused on data-rich period."""
    timestamps = [datetime.fromisoformat(e['timestamp'].rstrip('Z')) for e in events]
    
    if start_date_override:
        start_date = datetime.fromisoformat(start_date_override)
    else:
        # Find where 90% of events are
        sorted_ts = sorted(timestamps)
        start_idx = int(len(sorted_ts) * 0.05)  # Start at 5th percentile
        start_date = sorted_ts[start_idx]
    
    end_date = max(timestamps)
    
    print(f"  Animation period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    windows = []
    current = start_date
    while current + timedelta(days=window_days) <= end_date + timedelta(days=1):
        window_end = current + timedelta(days=window_days)
        windows.append({
            'start': current,
            'end': window_end,
            'start_str': current.isoformat() + 'Z',
            'end_str': window_end.isoformat() + 'Z'
        })
        current += timedelta(days=step_days)
    
    return windows


def fit_global_pca(storms, events, embedding_lookup):
    """Fit PCA once globally on all storm centroids."""
    centroids = []
    for storm in storms:
        event_embeddings = []
        for event_id in storm['event_ids']:
            if event_id in embedding_lookup:
                event_embeddings.append(embedding_lookup[event_id])
        if event_embeddings:
            centroids.append(np.mean(event_embeddings, axis=0))
    
    if not centroids:
        return None
    
    pca = PCA(n_components=2)
    pca.fit(np.array(centroids))
    return pca


def project_events_storms(events, storms, embedding_lookup, pca):
    """Project events and storms using fixed PCA."""
    for event in events:
        if event['event_id'] in embedding_lookup:
            emb = embedding_lookup[event['event_id']]
            proj = pca.transform([emb])[0]
            event['semantic_y'] = float(proj[0])
            event['semantic_c'] = float(proj[1])
            event['time_x'] = date2num(datetime.fromisoformat(event['timestamp'].rstrip('Z')))
    
    for storm in storms:
        event_embeddings = []
        for event_id in storm['event_ids']:
            if event_id in embedding_lookup:
                event_embeddings.append(embedding_lookup[event_id])
        if event_embeddings:
            centroid = np.mean(event_embeddings, axis=0)
            proj = pca.transform([centroid])[0]
            storm['semantic_y'] = float(proj[0])
            storm['semantic_c'] = float(proj[1])
            # Parse timestamps properly
            start_str = storm['created_at'].rstrip('Z').replace('+00:00', '')
            end_str = storm['updated_at'].rstrip('Z').replace('+00:00', '')
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)
            storm['time_x'] = date2num(start + (end - start) / 2)


def get_window_data(window, events, storms, cumulative=True):
    """Get events and storms up to window end (cumulative view)."""
    ws = window['start'].replace(tzinfo=None) if hasattr(window['start'], 'tzinfo') and window['start'].tzinfo else window['start']
    we = window['end'].replace(tzinfo=None) if hasattr(window['end'], 'tzinfo') and window['end'].tzinfo else window['end']
    
    window_events = []
    for event in events:
        event_time = datetime.fromisoformat(event['timestamp'].rstrip('Z'))
        # Only include events between window start and end (not before)
        if ws <= event_time < we:
            if event.get('semantic_y') is not None:
                window_events.append(event)
    
    window_storms = []
    for storm in storms:
        storm_start_str = storm['created_at'].rstrip('Z').replace('+00:00', '')
        storm_start = datetime.fromisoformat(storm_start_str)
        
        # Only include storms that started within or after window start
        if ws <= storm_start < we:
            if storm.get('semantic_y') is not None:
                window_storms.append(storm)
    
    return window_events, window_storms


def compute_density_for_window(window_events, x_min, x_max, y_min, y_max, grid_x=250, grid_y=180, sigma=1.6):
    """Compute density field for window events."""
    if not window_events:
        return None, None, None
    
    all_x = [e['time_x'] for e in window_events]
    all_y = [e['semantic_y'] for e in window_events]
    
    density, x_edges, y_edges = np.histogram2d(
        all_x, all_y,
        bins=[grid_x, grid_y],
        range=[[x_min, x_max], [y_min, y_max]]
    )
    
    density_smooth = gaussian_filter(density, sigma=sigma)
    x_grid = (x_edges[:-1] + x_edges[1:]) / 2
    y_grid = (y_edges[:-1] + y_edges[1:]) / 2
    
    return density_smooth, x_grid, y_grid


def plot_frame(window, all_events_so_far, all_storms_so_far, x_lim, y_lim, vmin, vmax, 
               density_data=None, frame_num=None, total_frames=None):
    """Plot a single animation frame with cumulative elements."""
    fig, ax = plt.subplots(figsize=(16, 10))
    
    cmap = plt.cm.coolwarm
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    
    # Plot density background (cumulative)
    if density_data is not None and density_data[0] is not None:
        density_smooth, x_grid, y_grid = density_data
        X, Y = np.meshgrid(x_grid, y_grid)
        ax.imshow(density_smooth.T, origin='lower',
                 extent=[x_grid[0], x_grid[-1], y_grid[0], y_grid[-1]],
                 cmap='Greys', alpha=0.22, aspect='auto', zorder=0)
        
        levels = np.linspace(density_smooth.min(), density_smooth.max(), 7)[1:-1]
        ax.contour(X, Y, density_smooth.T, levels=levels,
                  colors='gray', linewidths=0.5, alpha=0.3, zorder=0)
    
    # Plot ALL events accumulated so far
    for event in all_events_so_far:
        color = cmap(norm(event['semantic_c']))
        ax.scatter(event['time_x'], event['semantic_y'],
                  s=10, alpha=0.3, color=color, zorder=1)
    
    # Draw trajectory lines ONLY for storms that have appeared so far
    storm_positions = {}
    for storm in all_storms_so_far:  # Only use storms shown so far
        if storm.get('time_x') and storm.get('semantic_y'):
            actor = storm['actor']
            if actor not in storm_positions:
                storm_positions[actor] = []
            storm_positions[actor].append((storm['time_x'], storm['semantic_y']))
    
    for actor, positions in storm_positions.items():
        if len(positions) >= 2:
            positions.sort(key=lambda p: p[0])  # Sort by time
            xs, ys = zip(*positions)
            ax.plot(xs, ys, color='gray', linewidth=1.5, alpha=0.3, linestyle='--', zorder=1.5)
    
    # Plot ALL storms accumulated so far
    for storm in all_storms_so_far:
        color = cmap(norm(storm['semantic_c']))
        
        start_str = storm['created_at'].rstrip('Z').replace('+00:00', '')
        end_str = storm['updated_at'].rstrip('Z').replace('+00:00', '')
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        width = max((end - start).days * 0.8, 0.5)
        
        # Use all events for height calculation
        storm_events = [e for e in all_events_so_far if e['event_id'] in storm['event_ids']]
        if storm_events:
            y_values = [e['semantic_y'] for e in storm_events]
            height = max(np.std(y_values) * 4, 0.5)
        else:
            height = 0.5
        
        ellipse = patches.Ellipse(
            (storm['time_x'], storm['semantic_y']),
            width=width, height=height,
            fill=True, facecolor=color, edgecolor=color,
            linewidth=2, alpha=0.2, zorder=2
        )
        ax.add_patch(ellipse)
        
        # Add storm label with word wrap
        if storm.get('representative_events'):
            title = storm['representative_events'][0]['title']
            # Word wrap at 20 characters
            import textwrap
            wrapped = textwrap.fill(title, width=20)
            ax.text(storm['time_x'], storm['semantic_y'] + height/2 + 0.05,
                   wrapped, fontsize=6, ha='center', va='bottom',
                   bbox=dict(boxstyle='round,pad=0.2', facecolor='white', 
                            edgecolor=color, alpha=0.7), zorder=4)
    
    # Set fixed limits
    ax.set_xlim(x_lim)
    ax.set_ylim(y_lim)
    
    # Formatting
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Semantic Position (Dimension 1)', fontsize=12)
    
    title = f"Storm Field Evolution — Cumulative View\n"
    title += f"Through {window['end'].strftime('%Y-%m-%d')} "
    title += f"({len(all_events_so_far)} events, {len(all_storms_so_far)} storms)"
    ax.set_title(title, fontsize=14, fontweight='bold')
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    plt.xticks(rotation=45, ha='right')
    
    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, pad=0.02)
    cbar.set_label('Semantic Position (Dimension 2)', fontsize=11)
    
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    
    # Convert to image
    fig.canvas.draw()
    image = np.array(fig.canvas.renderer.buffer_rgba())
    image = image[:, :, :3]  # Drop alpha channel
    plt.close(fig)
    
    return image
