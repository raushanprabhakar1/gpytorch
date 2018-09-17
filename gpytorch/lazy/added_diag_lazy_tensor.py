from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import torch
from .non_lazy_tensor import NonLazyTensor
from .sum_lazy_tensor import SumLazyTensor
from .diag_lazy_tensor import DiagLazyTensor
from ..utils import pivoted_cholesky, batch_potrf
from .. import settings


class AddedDiagLazyTensor(SumLazyTensor):
    """
    A SumLazyTensor, but of only two lazy tensors, the second of which must be
    a DiagLazyTensor.
    """

    def __init__(self, *lazy_vars):
        lazy_vars = list(lazy_vars)
        super(AddedDiagLazyTensor, self).__init__(*lazy_vars)
        if len(lazy_vars) > 2:
            raise RuntimeError("An AddedDiagLazyTensor can only have two components")

        if isinstance(lazy_vars[0], DiagLazyTensor) and isinstance(lazy_vars[1], DiagLazyTensor):
            raise RuntimeError("Trying to lazily add two DiagLazyTensors. " "Create a single DiagLazyTensor instead.")
        elif isinstance(lazy_vars[0], DiagLazyTensor):
            self._diag_var = lazy_vars[0]
            self._lazy_var = lazy_vars[1]
        elif isinstance(lazy_vars[1], DiagLazyTensor):
            self._diag_var = lazy_vars[1]
            self._lazy_var = lazy_vars[0]
        else:
            raise RuntimeError("One of the LazyTensors input to AddedDiagLazyTensor " " must be a DiagLazyTensor!")

    def add_diag(self, added_diag):
        return AddedDiagLazyTensor(self._lazy_var, self._diag_var.add_diag(added_diag))

    def _preconditioner(self):
        if settings.max_preconditioner_size.value() == 0:
            return None, None

        if not hasattr(self, "_woodbury_cache"):
            max_iter = settings.max_preconditioner_size.value()
            self._piv_chol_self = pivoted_cholesky.pivoted_cholesky(self._lazy_var, max_iter)
            self._woodbury_cache = pivoted_cholesky.woodbury_factor(self._piv_chol_self, self._diag_var.diag())

        # preconditioner
        def precondition_closure(tensor):
            return pivoted_cholesky.woodbury_solve(
                tensor, self._piv_chol_self, self._woodbury_cache, self._diag_var.diag()
            )

        # log_det correction
        if not hasattr(self, "_precond_log_det_cache"):
            lr_flipped = self._piv_chol_self.matmul(
                self._piv_chol_self.transpose(-2, -1).div(self._diag_var.diag().unsqueeze(-1))
            )
            lr_flipped = lr_flipped + torch.eye(n=lr_flipped.size(-2), dtype=lr_flipped.dtype, device=lr_flipped.device)
            if lr_flipped.ndimension() == 3:
                ld_one = (NonLazyTensor(batch_potrf(lr_flipped)).diag().log().sum()) * 2
            else:
                ld_one = lr_flipped.potrf().diag().log().sum() * 2
            ld_two = self._diag_var.diag().log().sum().item()
            self._precond_log_det_cache = ld_one + ld_two

        return precondition_closure, self._precond_log_det_cache
