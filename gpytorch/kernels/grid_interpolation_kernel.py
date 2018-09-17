from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import torch
from .kernel import Kernel
from .grid_kernel import GridKernel
from ..lazy import InterpolatedLazyTensor
from ..utils import Interpolation


class GridInterpolationKernel(GridKernel):
    def __init__(self, base_kernel_module, grid_size, grid_bounds, active_dims=None):
        grid = torch.zeros(len(grid_bounds), grid_size)
        for i in range(len(grid_bounds)):
            grid_diff = float(grid_bounds[i][1] - grid_bounds[i][0]) / (grid_size - 2)
            grid[i] = torch.linspace(grid_bounds[i][0] - grid_diff, grid_bounds[i][1] + grid_diff, grid_size)

        inducing_points = torch.zeros(int(pow(grid_size, len(grid_bounds))), len(grid_bounds))
        prev_points = None
        for i in range(len(grid_bounds)):
            for j in range(grid_size):
                inducing_points[j * grid_size ** i : (j + 1) * grid_size ** i, i].fill_(grid[i, j])
                if prev_points is not None:
                    inducing_points[j * grid_size ** i : (j + 1) * grid_size ** i, :i].copy_(prev_points)
            prev_points = inducing_points[: grid_size ** (i + 1), : (i + 1)]

        super(GridInterpolationKernel, self).__init__(
            base_kernel_module=base_kernel_module, inducing_points=inducing_points, grid=grid, active_dims=active_dims
        )

    @property
    def has_custom_exact_predictions(self):
        return True

    def _compute_grid(self, inputs):
        batch_size, n_data, n_dimensions = inputs.size()
        inputs = inputs.view(batch_size * n_data, n_dimensions)
        interp_indices, interp_values = Interpolation().interpolate(self.grid, inputs)
        interp_indices = interp_indices.view(batch_size, n_data, -1)
        interp_values = interp_values.view(batch_size, n_data, -1)
        return interp_indices, interp_values

    def _inducing_forward(self):
        return super(GridInterpolationKernel, self).forward(self.inducing_points, self.inducing_points)

    def forward_diag(self, x1, x2, **kwargs):
        return super(Kernel, self).__call__(x1, x2, **kwargs).diag().unsqueeze(-1)

    def forward(self, x1, x2, **kwargs):
        base_lazy_tsr = self._inducing_forward()
        if x1.size(0) > 1:
            base_lazy_tsr = base_lazy_tsr.repeat(x1.size(0), 1, 1)

        left_interp_indices, left_interp_values = self._compute_grid(x1)
        if torch.equal(x1, x2):
            right_interp_indices = left_interp_indices
            right_interp_values = left_interp_values
        else:
            right_interp_indices, right_interp_values = self._compute_grid(x2)
        return InterpolatedLazyTensor(
            base_lazy_tsr,
            left_interp_indices.detach(),
            left_interp_values,
            right_interp_indices.detach(),
            right_interp_values,
        )
