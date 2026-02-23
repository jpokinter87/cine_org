"""Commande CLI fix-bad-links : corrige les symlinks mal lies (cible incorrecte).

Detecte les symlinks de series dont plusieurs episodes pointent vers le meme
fichier cible, puis recherche le bon fichier dans le storage pour chaque episode.
"""

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from src.adapters.cli.validation import console
from src.container import Container
from src.utils.constants import VIDEO_EXTENSIONS

# Pattern SxxExx dans un nom de fichier
_SXXEXX_RE = re.compile(r"S(\d+)E(\d+)", re.IGNORECASE)


def _find_duplicate_targets(
    video_dir: Path,
) -> dict[str, list[Path]]:
    """
    Trouve les symlinks partageant la meme cible physique.

    Parcourt video_dir recursivement, groupe les symlinks par cible resolue,
    et retourne seulement les groupes ayant plus d'un symlink.

    Returns:
        Dict {cible_resolue: [symlinks]} pour les cibles avec >= 2 symlinks.
    """
    target_to_links: dict[str, list[Path]] = defaultdict(list)

    for subdir_name in ("Films", "Séries"):
        subdir = video_dir / subdir_name
        if not subdir.exists():
            continue
        for symlink in subdir.rglob("*"):
            if not symlink.is_symlink():
                continue
            if symlink.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            try:
                # Lire la cible directe du symlink
                raw_target = os.readlink(symlink)
                if os.path.isabs(raw_target):
                    target = raw_target
                else:
                    target = str(symlink.parent / raw_target)
                # Verifier que la cible existe (on ne cherche que les liens non-casses)
                if Path(target).exists():
                    target_to_links[target].append(symlink)
            except OSError:
                continue

    # Ne garder que les cibles avec plusieurs symlinks
    return {t: links for t, links in target_to_links.items() if len(links) > 1}


def _match_episode_id(filename: str, season: int, episode: int) -> bool:
    """
    Verifie si un nom de fichier correspond exactement a un numero d'episode.

    Gere les formats SxxExx, SxxExxxx (3 chiffres) et evite les faux positifs
    (ex: S04E02 ne doit pas matcher S04E021).
    """
    upper = filename.upper()
    # Chercher tous les SxxExx dans le nom de fichier candidat
    for m in _SXXEXX_RE.finditer(upper):
        s = int(m.group(1))
        e = int(m.group(2))
        if s == season and e == episode:
            return True
    return False


def _find_correct_target_in_storage(
    link: Path, series_storage_dir: Path
) -> Path | None:
    """
    Recherche le bon fichier cible pour un symlink dans le repertoire storage de la serie.

    Extrait le SxxExx du nom du symlink et cherche un fichier correspondant
    dans l'arborescence du storage (recursivement via les Saison XX/).

    Args:
        link: Symlink a corriger
        series_storage_dir: Repertoire racine de la serie dans le storage

    Returns:
        Chemin du fichier cible correct ou None si introuvable.
    """
    match = _SXXEXX_RE.search(link.name)
    if not match:
        return None

    season = int(match.group(1))
    episode = int(match.group(2))

    if not series_storage_dir.exists():
        return None

    for candidate in series_storage_dir.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if _match_episode_id(candidate.name, season, episode):
            return candidate

    return None


def _get_series_storage_dir(target_path: Path) -> Path | None:
    """
    Determine le repertoire serie dans le storage depuis le chemin cible.

    Remonte l'arborescence depuis le fichier cible jusqu'au dossier
    parent d'un repertoire 'Saison XX'.

    Ex: /media/NAS64/Séries/M-O/Mr/Mr Selfridge (2013)/Saison 01/fichier.mkv
        → /media/NAS64/Séries/M-O/Mr/Mr Selfridge (2013)
    """
    target = Path(target_path)
    for i, part in enumerate(target.parts):
        if part.startswith("Saison"):
            return Path(*target.parts[:i])
    # Fallback : parent du fichier
    return target.parent


def fix_bad_links(
    scan_dir: Annotated[
        Optional[Path],
        typer.Argument(
            help="Repertoire a scanner (defaut: video_dir de la config)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Affiche les corrections sans les appliquer",
        ),
    ] = False,
) -> None:
    """
    Corrige les symlinks de series mal lies (plusieurs episodes → meme fichier).

    Detecte les groupes de symlinks partageant la meme cible, extrait le SxxExx
    de chaque symlink, et recherche le bon fichier dans le storage.

    Exemples:
      cineorg fix-bad-links                  # Corrige dans video_dir
      cineorg fix-bad-links --dry-run        # Simulation sans modification
      cineorg fix-bad-links /path/to/video   # Scanner un repertoire specifique
    """
    container = Container()
    config = container.config()
    video_dir = scan_dir or Path(config.video_dir)

    if not video_dir.exists():
        console.print(f"[red]Erreur : le repertoire {video_dir} n'existe pas.[/red]")
        raise typer.Exit(1)

    # Phase 1 : Detection des symlinks dupliques
    console.print("[bold]Phase 1 : Detection des symlinks partageant la meme cible[/bold]")

    with console.status("[cyan]Scan des symlinks..."):
        duplicates = _find_duplicate_targets(video_dir)

    if not duplicates:
        console.print("[green]Aucun symlink duplique detecte.[/green]")
        return

    # Compter le total de symlinks concernes
    total_links = sum(len(links) for links in duplicates.values())
    console.print(
        f"  [yellow]{len(duplicates)}[/yellow] cible(s) partagee(s) par "
        f"[yellow]{total_links}[/yellow] symlinks"
    )

    # Phase 2 : Correction des symlinks
    console.print()
    mode_label = "[dim](dry-run)[/dim] " if dry_run else ""
    console.print(f"{mode_label}[bold]Phase 2 : Correction des symlinks[/bold]")

    fixed = 0
    already_correct = 0
    not_found = 0
    skipped_no_episode = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Correction...", total=total_links)

        for target_path, links in duplicates.items():
            # Determiner le repertoire serie dans le storage
            series_dir = _get_series_storage_dir(Path(target_path))
            if not series_dir:
                not_found += len(links)
                progress.advance(task, len(links))
                continue

            for link in links:
                progress.update(task, description=f"[cyan]{link.name}")

                # Extraire SxxExx du symlink
                match = _SXXEXX_RE.search(link.name)
                if not match:
                    # Pas de SxxExx = probablement un film, ignorer silencieusement
                    skipped_no_episode += 1
                    progress.advance(task)
                    continue

                season = int(match.group(1))
                episode = int(match.group(2))

                # Verifier si le lien actuel est deja correct
                current_target = Path(target_path)
                if _match_episode_id(current_target.name, season, episode):
                    already_correct += 1
                    progress.advance(task)
                    continue

                # Chercher le bon fichier dans le storage
                correct_target = _find_correct_target_in_storage(link, series_dir)
                if not correct_target:
                    not_found += 1
                    console.print(
                        f"  [yellow]Introuvable[/yellow] : {link.name} "
                        f"(cherche S{season:02d}E{episode:02d} dans {series_dir.name})"
                    )
                    progress.advance(task)
                    continue

                if dry_run:
                    console.print(
                        f"  [cyan]A corriger[/cyan] : {link.name}\n"
                        f"    [dim]{current_target.name}[/dim] → "
                        f"[green]{correct_target.name}[/green]"
                    )
                    fixed += 1
                else:
                    try:
                        link.unlink()
                        link.symlink_to(correct_target)
                        fixed += 1
                        console.print(
                            f"  [green]Corrige[/green] : {link.name} → {correct_target.name}"
                        )
                    except OSError as e:
                        errors += 1
                        console.print(f"  [red]Erreur[/red] : {link.name} : {e}")

                progress.advance(task)

    # Resume
    console.print()
    console.print("[bold]Resume :[/bold]")
    action = "a corriger" if dry_run else "corriges"
    console.print(f"  Symlinks {action} : [green]{fixed}[/green]")
    if already_correct:
        console.print(f"  Deja corrects : [dim]{already_correct}[/dim]")
    if skipped_no_episode:
        console.print(f"  Ignores (films/pas de SxxExx) : [dim]{skipped_no_episode}[/dim]")
    if not_found:
        console.print(f"  Cible introuvable : [yellow]{not_found}[/yellow]")
    if errors:
        console.print(f"  Erreurs : [red]{errors}[/red]")
