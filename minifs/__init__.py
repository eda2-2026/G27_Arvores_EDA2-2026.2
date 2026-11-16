"""MiniFS: sistema de arquivos em memória construído sobre árvores (EDA2 — G27)."""

from .avl import AVLTree, Rotation
from .filesystem import FileSystem, FileSystemError
from .node import Node
from .shell import Shell

__all__ = ["AVLTree", "Rotation", "FileSystem", "FileSystemError", "Node", "Shell"]
