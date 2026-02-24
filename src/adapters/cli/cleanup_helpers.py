"""
Helpers CLI pour la commande cleanup.

Ce module fournit les fonctions utilitaires pour l'affichage des rapports
de nettoyage et des arbres detailles.

Responsabilites:
- Affichage du rapport de cleanup sous forme de tableau
- Affichage des arbres detailles par categorie
- Gestion du cache de rapport
"""

from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table
from rich.tree import Tree

if TYPE_CHECKING:
    from src.services.cleanup import CleanupReport


def display_cleanup_report(report: "CleanupReport", video_dir: Path) -> None:
    """
    Affiche le rapport de cleanup sous forme de tableau Rich.

    Args:
        report: Rapport de nettoyage a afficher
        video_dir: Repertoire video pour les chemins relatifs
    """
    from src.adapters.cli.helpers import console

    table = Table(title="Rapport de nettoyage", show_header=True)
    table.add_column("Categorie", style="cyan")
    table.add_column("Nombre", justify="right")
    table.add_column("Details", style="dim")

    table.add_row(
        "Symlinks casses",
        str(len(report.broken_symlinks)),
        f"{sum(1 for b in report.broken_symlinks if b.best_candidate)} reparables"
        if report.broken_symlinks else "",
    )
    table.add_row(
        "Symlinks mal places",
        str(len(report.misplaced_symlinks)),
        "",
    )
    table.add_row(
        "Symlinks dupliques",
        str(len(report.duplicate_symlinks)),
        ", ".join(
            f"{d.keep.name}" for d in report.duplicate_symlinks[:3]
        ) if report.duplicate_symlinks else "",
    )
    table.add_row(
        "Repertoires surcharges",
        str(len(report.oversized_dirs)),
        ", ".join(f"{p.parent_dir.name} ({p.current_count})" for p in report.oversized_dirs[:3])
        if report.oversized_dirs else "",
    )
    table.add_row(
        "Repertoires vides",
        str(len(report.empty_dirs)),
        "",
    )

    if report.not_in_db_count > 0:
        table.add_row(
            "Non references en BDD",
            str(report.not_in_db_count),
            "(ignores)",
        )

    console.print(table)

    # Arbres detailles par categorie
    if report.broken_symlinks:
        display_broken_symlinks_tree(report, video_dir)
    if report.misplaced_symlinks:
        display_misplaced_symlinks_tree(report, video_dir)
    if report.duplicate_symlinks:
        display_duplicate_symlinks_tree(report, video_dir)
    if report.oversized_dirs:
        display_oversized_dirs_tree(report, video_dir)
    if report.empty_dirs:
        display_empty_dirs_tree(report, video_dir)


def _rel_parent(path: Path, video_dir: Path) -> str:
    """Chemin parent relatif a video_dir, ou absolu si hors scope."""
    try:
        return str(path.parent.relative_to(video_dir))
    except ValueError:
        return str(path.parent)


def display_broken_symlinks_tree(report: "CleanupReport", video_dir: Path) -> None:
    """Affiche l'arbre detaille des symlinks casses groupes par repertoire."""
    from collections import defaultdict
    from src.adapters.cli.helpers import console

    console.print()

    groups: dict[str, list] = defaultdict(list)
    for b in report.broken_symlinks:
        groups[_rel_parent(b.symlink_path, video_dir)].append(b)

    tree = Tree(f"[bold red]Symlinks casses ({len(report.broken_symlinks)})[/bold red]")

    for dir_path in sorted(groups.keys()):
        dir_branch = tree.add(f"[cyan]{dir_path}/[/cyan]")
        for b in sorted(groups[dir_path], key=lambda x: x.symlink_path.name):
            name = b.symlink_path.name
            target_name = b.original_target.name if b.original_target != Path("") else "?"

            if b.best_candidate and b.candidate_score >= 90.0:
                label = (
                    f"[red]{name}[/red] -> [dim strikethrough]{target_name}[/dim strikethrough]"
                    f"  [green]reparable ({b.candidate_score:.0f}%): {b.best_candidate.name}[/green]"
                )
            elif b.best_candidate:
                label = (
                    f"[red]{name}[/red] -> [dim strikethrough]{target_name}[/dim strikethrough]"
                    f"  [yellow]candidat ({b.candidate_score:.0f}%): {b.best_candidate.name}[/yellow]"
                )
            else:
                label = (
                    f"[red]{name}[/red] -> [dim strikethrough]{target_name}[/dim strikethrough]"
                    f"  [dim]aucun candidat[/dim]"
                )
            dir_branch.add(label)

    console.print(tree)


def display_misplaced_symlinks_tree(report: "CleanupReport", video_dir: Path) -> None:
    """Affiche l'arbre des symlinks mal places avec deplacement prevu."""
    from collections import defaultdict
    from src.adapters.cli.helpers import console

    console.print()

    groups: dict[str, list] = defaultdict(list)
    for m in report.misplaced_symlinks:
        groups[_rel_parent(m.symlink_path, video_dir)].append(m)

    tree = Tree(
        f"[bold yellow]Symlinks mal places ({len(report.misplaced_symlinks)})[/bold yellow]"
    )

    for dir_path in sorted(groups.keys()):
        dir_branch = tree.add(f"[cyan]{dir_path}/[/cyan]")
        for m in sorted(groups[dir_path], key=lambda x: x.symlink_path.name):
            try:
                expected_rel = str(m.expected_dir.relative_to(video_dir))
            except ValueError:
                expected_rel = str(m.expected_dir)
            dir_branch.add(
                f"[yellow]{m.symlink_path.name}[/yellow]"
                f"  -> [green]{expected_rel}/[/green]"
            )

    console.print(tree)


def display_duplicate_symlinks_tree(report: "CleanupReport", video_dir: Path) -> None:
    """Affiche l'arbre des symlinks dupliques avec conservation/suppression."""
    from collections import defaultdict
    from src.adapters.cli.helpers import console

    console.print()

    groups: dict[str, list] = defaultdict(list)
    for d in report.duplicate_symlinks:
        try:
            rel_dir = str(d.directory.relative_to(video_dir))
        except ValueError:
            rel_dir = str(d.directory)

        groups[rel_dir].append(d)

    tree = Tree(
        f"[bold magenta]Symlinks dupliques ({len(report.duplicate_symlinks)})[/bold magenta]"
    )

    for dir_path in sorted(groups.keys()):
        dir_branch = tree.add(f"[cyan]{dir_path}/[/cyan]")
        for d in sorted(groups[dir_path], key=lambda x: x.symlink_path.name):
            keep_name = d.keep.name
            remove_names = ", ".join(s.name for s in d.remove)
            dir_branch.add(
                f"[green]{keep_name}[/green]  [dim]([/dim][red]{remove_names}[/red][dim])[/dim]"
            )

    console.print(tree)


def display_oversized_dirs_tree(report: "CleanupReport", video_dir: Path) -> None:
    """Affiche l'arbre des repertoires surcharges avec subdivision prevue."""
    from src.adapters.cli.helpers import console

    console.print()

    tree = Tree(
        f"[bold cyan]Repertoires surcharges ({len(report.oversized_dirs)})[/bold cyan]"
    )

    for p in sorted(report.oversized_dirs, key=lambda x: x.parent_dir):
        try:
            rel_dir = str(p.parent_dir.relative_to(video_dir))
        except ValueError:
            rel_dir = str(p.parent_dir)

        label = f"{rel_dir}/  [dim]({p.current_count} fichiers, max={p.max_files})[/dim]"
        dir_branch = tree.add(label)

        # Afficher les subdivisions creees
        if p.subdirs_created:
            for subdir in sorted(p.subdirs_created):
                dir_branch.add(f"[green]+ {subdir}/[/green]")

    console.print(tree)


def display_empty_dirs_tree(report: "CleanupReport", video_dir: Path) -> None:
    """Affiche l'arbre des repertoires vides a supprimer."""
    from src.adapters.cli.helpers import console

    console.print()

    tree = Tree(
        f"[dim]Repertoires vides ({len(report.empty_dirs)})[/dim]"
    )

    for empty_dir in sorted(report.empty_dirs):
        try:
            rel_dir = str(empty_dir.relative_to(video_dir))
        except ValueError:
            rel_dir = str(empty_dir)
        tree.add(f"[dim]{rel_dir}/[/dim]")

    console.print(tree)
