"""Fixed-XY review views. Detection outputs and recorded trace coordinates stay intact."""
from pathlib import Path
import collections
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ALIGNMENT_VERSION = 4


def track_geometry(x, y):
    points = np.column_stack((x, y)).astype(float)
    if len(points) < 2 or not np.isfinite(points).all():
        raise ValueError('Track coordinates are missing or invalid; spatial alignment is unavailable.')
    delta = np.diff(points, axis=0)
    length = np.linalg.norm(delta, axis=1)
    positive = length[length > 1e-9]
    if not len(positive):
        raise ValueError('Track coordinates contain no valid displacement; spatial alignment is unavailable.')
    spacing = float(np.median(positive))
    # A discontinuity is excluded from interpolation, rather than drawing across it.
    breaks = length > spacing * 10
    valid = (length > 1e-9) & ~breaks
    if not valid.any():
        raise ValueError('The track has no continuous segment with valid coordinates.')
    return dict(points=points, delta=delta, length=length, valid=valid,
                breaks=breaks, spacing=spacing, s=np.r_[0., np.cumsum(length)])


def project_to_track(track, target, preferred_trace=None):
    points, delta = track['points'], track['delta']
    relative = np.asarray(target, float) - points[:-1]
    squared = track['length'] ** 2
    fraction = np.clip(np.sum(relative * delta, axis=1) / np.maximum(squared, 1e-20), 0, 1)
    projected = points[:-1] + fraction[:, None] * delta
    distance = np.linalg.norm(projected - target, axis=1)
    distance[~track['valid']] = np.inf
    minimum = float(distance.min())
    # Half a trace spacing is a sampling-resolution tolerance, not a GPS accuracy claim.
    tolerance = max(track['spacing'] / 2, 1e-6)
    near = np.flatnonzero(distance <= minimum + tolerance)
    clusters = np.split(near, np.flatnonzero(np.diff(near) > 1) + 1)
    choices = [int(group[np.argmin(distance[group])]) for group in clusters if len(group)]
    choices.sort(key=lambda index: (float(distance[index]), index))
    chosen = choices[0]
    resolved_by_anchor = False
    if preferred_trace is not None:
        # Only the primary source trace is known independently; other files remain flagged.
        anchored = min(choices, key=lambda index: abs(index + fraction[index] - preferred_trace))
        if distance[anchored] <= minimum + tolerance:
            chosen = anchored
            resolved_by_anchor = len(choices) > 1
    i = chosen
    nearest = i if fraction[i] < .5 else i + 1
    left_breaks = np.flatnonzero(track['breaks'][:i])
    right_breaks = np.flatnonzero(track['breaks'][i + 1:])
    lo = int(left_breaks[-1] + 1) if len(left_breaks) else 0
    hi = int(i + 1 + right_breaks[0]) if len(right_breaks) else len(points) - 1
    centre_s = float(track['s'][i] + fraction[i] * track['length'][i])
    # Use a ~1 m local trajectory direction to avoid millimetre quantization jitter.
    s = track['s']
    a = max(lo, int(np.searchsorted(s, centre_s - .5)))
    b = min(hi, int(np.searchsorted(s, centre_s + .5)))
    tangent = points[b] - points[a] if b > a else delta[i]
    if np.linalg.norm(tangent) < 1e-9:
        tangent = delta[i]
    tangent = tangent / np.linalg.norm(tangent)
    return dict(segment=i, fraction=float(fraction[i]), trace_0based=nearest,
                point=projected[i], distance_m=float(distance[i]), centre_s=centre_s,
                lo=lo, hi=hi, tangent=tangent,
                ambiguous=len(choices) > 1 and not resolved_by_anchor,
                alternatives=[dict(trace_1based=k + 1 + float(fraction[k]),
                                   distance_m=float(distance[k])) for k in choices],
                primary_trace_resolved=resolved_by_anchor)


def physical_window(samples, track, projection, half_m, reverse=False, width=401):
    """Uniform along-track metres, full vertical samples, missing coverage stays blank."""
    lo, hi = projection['lo'], projection['hi']
    distances = track['s'][lo:hi + 1]
    unique, local_indices = np.unique(distances, return_index=True)
    if len(unique) < 2:
        raise ValueError('Insufficient continuous track samples near the matching position.')
    target = projection['centre_s'] + np.linspace(-half_m, half_m, width) * (-1 if reverse else 1)
    inside = (target >= unique[0] - 1e-9) & (target <= unique[-1] + 1e-9)
    high = np.clip(np.searchsorted(unique, target, side='right'), 1, len(unique) - 1)
    low = high - 1
    weight = np.clip((target - unique[low]) / (unique[high] - unique[low]), 0, 1)
    low_id, high_id = local_indices[low] + lo, local_indices[high] + lo
    values = (samples[low_id].astype(np.float32) * (1 - weight[:, None]) +
              samples[high_id].astype(np.float32) * weight[:, None]).T.astype(np.float32)
    values[:, ~inside] = np.nan
    return values, float(inside.mean())


def render_panel(values, path, half_m, ai_offset_m, label):
    """Blue fixed XY projection and dashed green AI center, in the same scale."""
    finite = values[np.isfinite(values)]
    limit = float(np.percentile(np.abs(finite), 99)) if len(finite) else 1
    limit = limit or 1
    normalized = np.clip(values / limit, -1, 1)
    pixels = np.nan_to_num((normalized + 1) * 127.5, nan=42).astype('uint8')
    im = Image.new('RGB', (1100, 470), '#242024')
    im.paste(Image.fromarray(pixels).resize((1100, 400)).convert('RGB'), (0, 28))
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 14)
    except OSError:
        font = ImageFont.load_default(size=14)
    draw.text((12, 5), label, font=font, fill='#eee7e8')
    draw.line((550, 28, 550, 428), fill='#70b9f2', width=2)
    if ai_offset_m is not None and abs(ai_offset_m) <= half_m:
        column = round((ai_offset_m + half_m) / (2 * half_m) * 1099)
        for y in range(28, 428, 16):
            draw.line((column, y, column, min(y + 9, 427)), fill='#20c785', width=3)
    for offset in np.linspace(-half_m, half_m, 5):
        column = round((offset + half_m) / (2 * half_m) * 1099)
        text = f'{offset:+g} m' if offset else '0 m'
        draw.line((column, 428, column, 435), fill='#c9bfc2')
        text_width = draw.textbbox((0, 0), text, font=font)[2]
        draw.text((max(2, min(1097 - text_width, column - text_width / 2)), 438), text,
                  font=font, fill='#eee7e8')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, format='PNG', compress_level=3)


def build_aligned_comparison(job, candidate, rows, out, progress):
    from engine import read_sgy
    out = Path(out)
    target = (candidate.get('x'), candidate.get('y'))
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in target):
        raise ValueError('The primary candidate has no valid XY. The primary image is retained; other channels cannot be spatially aligned.')
    sources = {f['id']: f for f in job['input_files']}
    metas = {f['file_id']: f for f in job['files']}
    primary_meta = metas[candidate['file_id']]
    fallback = float(job['options'].get('spacing_m', .04))
    primary_source = sources[candidate['file_id']]
    _, px, py, _, pm = read_sgy(primary_source['path'], fallback)
    if not pm['coordinate_available']:
        raise ValueError('The primary channel has no reliable metric track coordinates for cross-channel alignment.')
    primary_track = track_geometry(px, py)
    primary_projection = project_to_track(primary_track, target, candidate['trace_1based'] - 1)
    reference_tangent = primary_projection['tangent']
    profiles = {candidate['profile']} | {r['profile'] for r in rows}
    selected = sorted((m for m in metas.values() if m['profile'] in profiles),
                      key=lambda m: (m['profile'] != candidate['profile'], m['profile'],
                                     m['channel'] is None, m['channel'] or 0, m['name']))
    aligned = collections.defaultdict(list)
    warnings = ['Aligned using recorded SGY source XY; absolute antenna positions and lever-arm calibration have not been independently verified.']
    audit = []
    for index, meta in enumerate(selected):
        progress(.05 + .93 * index / max(1, len(selected)),
                 f'Aligning coordinate windows {index + 1}/{len(selected)} · {meta["profile"]} CH{meta["channel"]}')
        source = sources[meta['file_id']]
        try:
            path = Path(source['path'])
            if not path.is_file() or (source.get('size') and path.stat().st_size != source['size']):
                raise ValueError('Source SGY is missing or its size has changed')
            samples, x, y, dx, current = read_sgy(path, fallback)
            if not current['coordinate_available']:
                raise ValueError('No reliable metric XY; trace-number matching was not used to guess a position')
            if (len(samples), samples.shape[1]) != (meta['traces'], meta['samples_per_trace']):
                raise ValueError('Source file sample layout has changed')
            track = track_geometry(x, y)
            projection = project_to_track(track, target,
                candidate['trace_1based'] - 1 if meta['file_id'] == candidate['file_id'] else None)
            dot = float(np.clip(np.dot(reference_tangent, projection['tangent']), -1, 1))
            reverse = dot < 0
            angle = math.degrees(math.acos(abs(dot)))
            small, coverage8 = physical_window(samples, track, projection, 4, reverse)
            large, coverage16 = physical_window(samples, track, projection, 8, reverse)
            closest = projection['trace_0based']
            shared = dict(alignment_version=ALIGNMENT_VERSION, alignment='nearest_track_projection',
                alignment_target_x=target[0], alignment_target_y=target[1],
                alignment_trace_1based=closest + 1,
                alignment_fractional_trace_1based=projection['segment'] + 1 + projection['fraction'],
                alignment_x=float(projection['point'][0]), alignment_y=float(projection['point'][1]),
                alignment_distance_m=projection['distance_m'],
                alignment_sample_x=float(x[closest]), alignment_sample_y=float(y[closest]),
                alignment_sample_distance_m=float(np.hypot(x[closest] - target[0], y[closest] - target[1])),
                alignment_ambiguous=projection['ambiguous'], alignment_choices=projection['alternatives'],
                alignment_primary_trace_resolved=projection['primary_trace_resolved'],
                display_reversed=reverse, relative_track_angle_degrees=angle,
                window_width_m=8, context_width_m=16, coverage_fraction=coverage8,
                context_coverage_fraction=coverage16, samples_per_trace=current['samples_per_trace'])
            members = [r for r in rows if r['file_id'] == meta['file_id']]
            if not members:
                members = [dict(file_id=meta['file_id'], name=meta['name'], profile=meta['profile'],
                    channel=meta['channel'], trace_1based=closest + 1,
                    window_center_trace_1based=closest + 1, x=float(x[closest]), y=float(y[closest]),
                    logit=None, spacing_m=dx, primary=False, distance_to_primary_m=None,
                    distance_kind='unknown', observation_id='R_' + meta['file_id'])]
            for member in members:
                merged = member.get('logit') is not None
                row = dict(member, **shared)
                ai_trace = member['trace_1based'] - 1
                ai_offset = ((float(track['s'][ai_trace]) - projection['centre_s']) * (-1 if reverse else 1)
                             if merged and projection['lo'] <= ai_trace <= projection['hi'] else None)
                row.update(view_kind='merged' if merged else 'reference', line_kind='spatial_alignment',
                    source_observation_id=member['observation_id'] if merged else None,
                    ai_offset_from_alignment_m=ai_offset,
                    ai_inside_window=ai_offset is not None and abs(ai_offset) <= 4,
                    original_file=member.get('file'), original_context_image=member.get('context_image'))
                stem=f'images/aligned_v4/{candidate["candidate_id"]}/{meta["file_id"]}/{member["observation_id"]}'
                row['file'], row['context_image'] = stem + '.png', stem + '_context.png'
                label=f'{candidate["candidate_id"]} | CH {meta["channel"]} | fixed primary XY | blue: alignment | green dashed: AI center'
                render_panel(small, out / row['file'], 4, ai_offset, label)
                render_panel(large, out / row['context_image'], 8, ai_offset, label)
                aligned[meta['profile']].append(row)
            if projection['ambiguous']:
                warnings.append(f'{meta["profile"]} CH{meta["channel"]} has multiple possible matching positions. The nearest segment is shown; check alignment.')
            audit.append(dict(file_id=meta['file_id'], profile=meta['profile'], channel=meta['channel'], **shared))
            del samples
        except (OSError, ValueError) as error:
            if meta['file_id'] == candidate['file_id']:
                raise
            warnings.append(f'{meta["profile"]} CH{meta["channel"]}: {error}; no image was generated at a guessed position.')
    main = []
    by_channel = collections.defaultdict(list)
    for row in aligned[candidate['profile']]:
        by_channel[row['channel'] if row['channel'] is not None else row['file_id']].append(row)
    for variants in by_channel.values():
        variants.sort(key=lambda r: (not r.get('primary'), r.get('distance_to_primary_m') is None,
                                     r.get('distance_to_primary_m') or 0, r['name'], r['trace_1based']))
        representative = dict(variants[0], aligned_alternatives=variants)
        representative['view_id'] = 'M_' + representative['file_id']
        main.append(representative)
    main.sort(key=lambda r: (r['channel'] is None, r['channel'] or 0, r['name']))
    groups = []
    for profile, views in aligned.items():
        if profile == candidate['profile']:
            continue
        views.sort(key=lambda r: (r['channel'] is None, r['channel'] or 0,
                                  r.get('distance_to_primary_m') is None, r.get('distance_to_primary_m') or 0))
        groups.append(dict(profile=profile, primary_swath=False, alignment_version=ALIGNMENT_VERSION,
            nearest_distance_m=min(r['alignment_distance_m'] for r in views), rows=views))
    groups.sort(key=lambda group: (group['nearest_distance_m'], group['profile']))
    present={r['source_observation_id'] for views in aligned.values() for r in views if r['source_observation_id']}
    missing={r['observation_id'] for r in rows} - present
    if missing:
        warnings.append(f'{len(missing)} merged observations have no usable alignment track. Historical records are preserved and are not shown as aligned images.')
    return dict(rows=rows, main_rows=main, groups=groups, warnings=warnings,
                alignment_audit=dict(version=ALIGNMENT_VERSION, target_xy=list(target),
                    reference_file_id=candidate['file_id'], coordinate_reference='recorded source XY',
                    antenna_calibration_verified=False, files=audit, missing_observation_ids=sorted(missing)))
