"""Commande CLI fix-symlinks : corrige les symlinks (relatifs→absolus, mal-placés→bon répertoire)."""

import os
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.adapters.cli.validation import console
from src.container import Container
from src.services.organizer import _find_matching_subdir, _navigate_to_leaf
from src.utils.constants import VIDEO_EXTENSIONS


def _extract_title_from_filename(filename: str) -> str:
    """
    Extrait le titre d'un nom de fichier vidéo.

    Utilise guessit pour parser le nom et en extraire le titre.
    Fallback sur le texte avant la première parenthèse.

    Args:
        filename: Nom du fichier (ex: "Marty Supreme (2025) MULTi x265 1080p.mkv").

    Returns:
        Titre extrait (ex: "Marty Supreme").
    """
    try:
        from guessit import guessit

        result = guessit(filename)
        if "title" in result:
            return result["title"]
    except Exception:
        pass

    # Fallback : texte avant la première parenthèse
    name = Path(filename).stem
    if "(" in name:
        return name[: name.index("(")].strip()
    return name.strip()


def _find_misplaced_symlinks(
    video_dir: Path,
) -> list[tuple[Path, Path]]:
    """
    Trouve les symlinks mal-placés dans Films/ et Séries/.

    Approche optimisée : au lieu de parser chaque fichier (~90k),
    on identifie les répertoires "mixtes" qui contiennent à la fois
    des sous-répertoires de subdivision ET des fichiers vidéo.
    Les fichiers vidéo dans ces répertoires sont forcément mal-placés.

    Args:
        video_dir: Répertoire racine des symlinks.

    Returns:
        Liste de tuples (symlink_actuel, destination_correcte).
    """
    misplaced = []

    # Déterminer les répertoires à scanner :
    # - Si video_dir contient Films/ ou Séries/, scanner ces sous-répertoires
    # - Sinon, scanner video_dir directement (l'utilisateur a ciblé un sous-répertoire)
    scan_dirs = []
    for subdir_name in ("Films", "Séries"):
        subdir = video_dir / subdir_name
        if subdir.exists():
            scan_dirs.append(subdir)

    if not scan_dirs:
        # video_dir est déjà un sous-répertoire (ex: /media/.../Films)
        scan_dirs = [video_dir]

    for scan_dir in scan_dirs:
        for dirpath in scan_dir.rglob("*"):
            if not dirpath.is_dir():
                continue

            # Lister le contenu du répertoire en une seule passe
            subdirs = []
            video_files = []
            try:
                for entry in dirpath.iterdir():
                    if entry.is_dir() and not entry.is_symlink():
                        subdirs.append(entry)
                    elif entry.is_symlink() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                        video_files.append(entry)
            except PermissionError:
                continue

            # Si pas de sous-répertoires, les fichiers sont à leur place (feuille)
            if not subdirs or not video_files:
                continue

            # Répertoire mixte : les fichiers vidéo doivent descendre plus profond
            for symlink in video_files:
                title = _extract_title_from_filename(symlink.name)
                if not title:
                    continue

                correct_dir = _navigate_to_leaf(dirpath, title)
                if correct_dir != dirpath:
                    misplaced.append((symlink, correct_dir / symlink.name))

    return misplaced


def fix_symlinks(
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
            help="Affiche les modifications sans les appliquer",
        ),
    ] = False,
) -> None:
    """Corrige les symlinks : convertit relatifs en absolus et relocalise les mal-placés."""
    container = Container()
    config = container.config()
    target_dir = scan_dir or config.video_dir

    if not target_dir.exists():
        console.print(f"[red]Erreur : le répertoire {target_dir} n'existe pas.[/red]")
        raise typer.Exit(1)

    # ── Phase 1 : Conversion relatif → absolu ──
    console.print("[bold]Phase 1 : Conversion des symlinks relatifs en absolus[/bold]")

    converted = 0
    already_absolute = 0
    broken = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description=f"Scan de {target_dir}...", total=None)

        for symlink in target_dir.rglob("*"):
            if not symlink.is_symlink():
                continue

            link_target = os.readlink(symlink)

            if os.path.isabs(link_target):
                already_absolute += 1
                continue

            resolved = symlink.resolve()

            if not resolved.exists():
                broken += 1
                console.print(
                    f"  [yellow]Cassé[/yellow] : {symlink.relative_to(target_dir)} → {link_target}"
                )
                continue

            if dry_run:
                console.print(
                    f"  [cyan]À convertir[/cyan] : {symlink.relative_to(target_dir)}"
                )
                console.print(f"    [dim]{link_target}[/dim] → [green]{resolved}[/green]")
                converted += 1
            else:
                try:
                    symlink.unlink()
                    symlink.symlink_to(resolved)
                    converted += 1
                except OSError as e:
                    errors += 1
                    console.print(
                        f"  [red]Erreur[/red] : {symlink.relative_to(target_dir)} : {e}"
                    )

    action = "à convertir" if dry_run else "convertis"
    console.print(f"  Symlinks {action} : [green]{converted}[/green]")
    console.print(f"  Déjà absolus : {already_absolute}")
    if broken:
        console.print(f"  Symlinks cassés (ignorés) : [yellow]{broken}[/yellow]")
    if errors:
        console.print(f"  Erreurs : [red]{errors}[/red]")

    # ── Phase 2 : Relocalisation des symlinks mal-placés ──
    console.print()
    console.print("[bold]Phase 2 : Relocalisation des symlinks mal-placés[/bold]")

    misplaced = _find_misplaced_symlinks(target_dir)

    if not misplaced:
        console.print("  Aucun symlink mal-placé détecté.")
        return

    relocated = 0
    reloc_errors = 0

    for symlink, correct_path in misplaced:
        rel_current = symlink.relative_to(target_dir)
        rel_correct = correct_path.relative_to(target_dir)

        if dry_run:
            console.print(f"  [cyan]À déplacer[/cyan] : {rel_current}")
            console.print(f"    → [green]{rel_correct}[/green]")
            relocated += 1
        else:
            try:
                # Lire la cible absolue du symlink
                link_target = os.readlink(symlink)
                if not os.path.isabs(link_target):
                    link_target = str(symlink.resolve())

                # Créer le répertoire destination si nécessaire
                correct_path.parent.mkdir(parents=True, exist_ok=True)

                # Supprimer l'ancien et créer le nouveau
                symlink.unlink()
                correct_path.symlink_to(link_target)
                relocated += 1

                console.print(f"  [green]Déplacé[/green] : {rel_current} → {rel_correct}")
            except OSError as e:
                reloc_errors += 1
                console.print(f"  [red]Erreur[/red] : {rel_current} : {e}")

    # Résumé phase 2
    console.print()
    action = "à déplacer" if dry_run else "déplacés"
    console.print(f"[bold]Résumé phase 2 :[/bold]")
    console.print(f"  Symlinks {action} : [green]{relocated}[/green]")
    if reloc_errors:
        console.print(f"  Erreurs : [red]{reloc_errors}[/red]")
