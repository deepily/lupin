#!/usr/bin/env python3
"""
Complex Calculations Script
============================
A comprehensive Python script demonstrating various complex mathematical computations
including linear algebra, statistics, numerical methods, signal processing, optimization,
differential equations, and more.

Author: Claude AI Assistant
"""

import math
import cmath
import random
import itertools
import functools
from typing import List, Tuple, Callable, Optional, Union, Dict, Any
from collections import defaultdict
from dataclasses import dataclass
import time


# =============================================================================
# SECTION 1: MATRIX OPERATIONS AND LINEAR ALGEBRA
# =============================================================================

class Matrix:
    """A class for matrix operations without external dependencies."""

    def __init__(self, data: List[List[float]]):
        """Initialize matrix with 2D list of numbers."""
        self.data = data
        self.rows = len(data)
        self.cols = len(data[0]) if data else 0
        self._validate()

    def _validate(self):
        """Ensure all rows have the same length."""
        for row in self.data:
            if len(row) != self.cols:
                raise ValueError("All rows must have the same length")

    @classmethod
    def identity(cls, n: int) -> 'Matrix':
        """Create an n x n identity matrix."""
        data = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        return cls(data)

    @classmethod
    def zeros(cls, rows: int, cols: int) -> 'Matrix':
        """Create a matrix of zeros."""
        return cls([[0.0 for _ in range(cols)] for _ in range(rows)])

    @classmethod
    def random(cls, rows: int, cols: int, low: float = 0, high: float = 1) -> 'Matrix':
        """Create a matrix with random values."""
        data = [[random.uniform(low, high) for _ in range(cols)] for _ in range(rows)]
        return cls(data)

    def __repr__(self) -> str:
        """String representation of matrix."""
        rows_str = []
        for row in self.data:
            row_str = "[" + ", ".join(f"{x:8.4f}" for x in row) + "]"
            rows_str.append(row_str)
        return "Matrix([\n  " + ",\n  ".join(rows_str) + "\n])"

    def __add__(self, other: 'Matrix') -> 'Matrix':
        """Matrix addition."""
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrices must have same dimensions for addition")
        result = [
            [self.data[i][j] + other.data[i][j] for j in range(self.cols)]
            for i in range(self.rows)
        ]
        return Matrix(result)

    def __sub__(self, other: 'Matrix') -> 'Matrix':
        """Matrix subtraction."""
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrices must have same dimensions for subtraction")
        result = [
            [self.data[i][j] - other.data[i][j] for j in range(self.cols)]
            for i in range(self.rows)
        ]
        return Matrix(result)

    def __mul__(self, other: Union['Matrix', float]) -> 'Matrix':
        """Matrix multiplication or scalar multiplication."""
        if isinstance(other, (int, float)):
            result = [[self.data[i][j] * other for j in range(self.cols)]
                      for i in range(self.rows)]
            return Matrix(result)

        if self.cols != other.rows:
            raise ValueError(f"Cannot multiply {self.rows}x{self.cols} by {other.rows}x{other.cols}")

        result = Matrix.zeros(self.rows, other.cols)
        for i in range(self.rows):
            for j in range(other.cols):
                total = 0.0
                for k in range(self.cols):
                    total += self.data[i][k] * other.data[k][j]
                result.data[i][j] = total
        return result

    def transpose(self) -> 'Matrix':
        """Return the transpose of the matrix."""
        result = [[self.data[j][i] for j in range(self.rows)] for i in range(self.cols)]
        return Matrix(result)

    def trace(self) -> float:
        """Calculate the trace of a square matrix."""
        if self.rows != self.cols:
            raise ValueError("Trace is only defined for square matrices")
        return sum(self.data[i][i] for i in range(self.rows))

    def determinant(self) -> float:
        """Calculate determinant using LU decomposition."""
        if self.rows != self.cols:
            raise ValueError("Determinant is only defined for square matrices")

        n = self.rows
        if n == 1:
            return self.data[0][0]
        if n == 2:
            return self.data[0][0] * self.data[1][1] - self.data[0][1] * self.data[1][0]

        # Create a copy for LU decomposition
        lu = [[self.data[i][j] for j in range(n)] for i in range(n)]
        det = 1.0

        for col in range(n):
            # Find pivot
            max_row = col
            for row in range(col + 1, n):
                if abs(lu[row][col]) > abs(lu[max_row][col]):
                    max_row = row

            if max_row != col:
                lu[col], lu[max_row] = lu[max_row], lu[col]
                det *= -1

            if abs(lu[col][col]) < 1e-12:
                return 0.0

            det *= lu[col][col]

            for row in range(col + 1, n):
                factor = lu[row][col] / lu[col][col]
                for j in range(col, n):
                    lu[row][j] -= factor * lu[col][j]

        return det

    def inverse(self) -> 'Matrix':
        """Calculate matrix inverse using Gauss-Jordan elimination."""
        if self.rows != self.cols:
            raise ValueError("Only square matrices can be inverted")

        n = self.rows
        augmented = [self.data[i] + [1.0 if i == j else 0.0 for j in range(n)]
                     for i in range(n)]

        # Forward elimination
        for col in range(n):
            # Find pivot
            max_row = col
            for row in range(col + 1, n):
                if abs(augmented[row][col]) > abs(augmented[max_row][col]):
                    max_row = row

            augmented[col], augmented[max_row] = augmented[max_row], augmented[col]

            if abs(augmented[col][col]) < 1e-12:
                raise ValueError("Matrix is singular and cannot be inverted")

            # Scale pivot row
            pivot = augmented[col][col]
            for j in range(2 * n):
                augmented[col][j] /= pivot

            # Eliminate column
            for row in range(n):
                if row != col:
                    factor = augmented[row][col]
                    for j in range(2 * n):
                        augmented[row][j] -= factor * augmented[col][j]

        result = [row[n:] for row in augmented]
        return Matrix(result)

    def lu_decomposition(self) -> Tuple['Matrix', 'Matrix']:
        """Perform LU decomposition with partial pivoting."""
        if self.rows != self.cols:
            raise ValueError("LU decomposition requires a square matrix")

        n = self.rows
        L = Matrix.identity(n)
        U = [[self.data[i][j] for j in range(n)] for i in range(n)]

        for col in range(n - 1):
            for row in range(col + 1, n):
                if abs(U[col][col]) < 1e-12:
                    continue
                factor = U[row][col] / U[col][col]
                L.data[row][col] = factor
                for j in range(col, n):
                    U[row][j] -= factor * U[col][j]

        return L, Matrix(U)

    def qr_decomposition(self) -> Tuple['Matrix', 'Matrix']:
        """Perform QR decomposition using Gram-Schmidt process."""
        n = self.rows
        m = self.cols

        Q = Matrix.zeros(n, m)
        R = Matrix.zeros(m, m)

        for j in range(m):
            # Start with column j
            v = [self.data[i][j] for i in range(n)]

            # Subtract projections onto previous columns
            for i in range(j):
                # Calculate dot product
                dot = sum(Q.data[k][i] * self.data[k][j] for k in range(n))
                R.data[i][j] = dot
                for k in range(n):
                    v[k] -= dot * Q.data[k][i]

            # Normalize
            norm = math.sqrt(sum(x * x for x in v))
            R.data[j][j] = norm

            if norm > 1e-12:
                for i in range(n):
                    Q.data[i][j] = v[i] / norm

        return Q, R

    def eigenvalues_power_method(self, num_iterations: int = 100) -> Tuple[float, List[float]]:
        """Find dominant eigenvalue using power iteration."""
        if self.rows != self.cols:
            raise ValueError("Eigenvalues require a square matrix")

        n = self.rows
        v = [random.random() for _ in range(n)]
        norm = math.sqrt(sum(x * x for x in v))
        v = [x / norm for x in v]

        eigenvalue = 0.0
        for _ in range(num_iterations):
            # Matrix-vector multiplication
            new_v = [sum(self.data[i][j] * v[j] for j in range(n)) for i in range(n)]

            # Find largest component for eigenvalue estimate
            max_idx = max(range(n), key=lambda i: abs(new_v[i]))
            if abs(v[max_idx]) > 1e-12:
                eigenvalue = new_v[max_idx] / v[max_idx]

            # Normalize
            norm = math.sqrt(sum(x * x for x in new_v))
            v = [x / norm for x in new_v]

        return eigenvalue, v

    def frobenius_norm(self) -> float:
        """Calculate the Frobenius norm of the matrix."""
        return math.sqrt(sum(self.data[i][j] ** 2
                            for i in range(self.rows)
                            for j in range(self.cols)))

    def condition_number(self) -> float:
        """Estimate condition number using power method."""
        eigenval1, _ = self.eigenvalues_power_method()
        inv = self.inverse()
        eigenval2, _ = inv.eigenvalues_power_method()
        return abs(eigenval1 * eigenval2)


# =============================================================================
# SECTION 2: NUMERICAL INTEGRATION AND DIFFERENTIATION
# =============================================================================

class NumericalMethods:
    """Collection of numerical methods for integration and differentiation."""

    @staticmethod
    def derivative(f: Callable[[float], float], x: float, h: float = 1e-8) -> float:
        """Calculate derivative using central difference method."""
        return (f(x + h) - f(x - h)) / (2 * h)

    @staticmethod
    def second_derivative(f: Callable[[float], float], x: float, h: float = 1e-5) -> float:
        """Calculate second derivative using central difference."""
        return (f(x + h) - 2 * f(x) + f(x - h)) / (h * h)

    @staticmethod
    def partial_derivative(f: Callable[..., float], args: List[float],
                          var_index: int, h: float = 1e-8) -> float:
        """Calculate partial derivative with respect to variable at var_index."""
        args_plus = args.copy()
        args_minus = args.copy()
        args_plus[var_index] += h
        args_minus[var_index] -= h
        return (f(*args_plus) - f(*args_minus)) / (2 * h)

    @staticmethod
    def gradient(f: Callable[..., float], args: List[float], h: float = 1e-8) -> List[float]:
        """Calculate gradient vector of a multivariable function."""
        return [NumericalMethods.partial_derivative(f, args, i, h)
                for i in range(len(args))]

    @staticmethod
    def hessian(f: Callable[..., float], args: List[float], h: float = 1e-5) -> Matrix:
        """Calculate Hessian matrix of a multivariable function."""
        n = len(args)
        H = Matrix.zeros(n, n)

        for i in range(n):
            for j in range(i, n):
                args_pp = args.copy()
                args_pm = args.copy()
                args_mp = args.copy()
                args_mm = args.copy()

                args_pp[i] += h
                args_pp[j] += h
                args_pm[i] += h
                args_pm[j] -= h
                args_mp[i] -= h
                args_mp[j] += h
                args_mm[i] -= h
                args_mm[j] -= h

                H.data[i][j] = (f(*args_pp) - f(*args_pm) - f(*args_mp) + f(*args_mm)) / (4 * h * h)
                H.data[j][i] = H.data[i][j]

        return H

    @staticmethod
    def trapezoidal_rule(f: Callable[[float], float], a: float, b: float, n: int) -> float:
        """Numerical integration using trapezoidal rule."""
        h = (b - a) / n
        result = 0.5 * (f(a) + f(b))
        for i in range(1, n):
            result += f(a + i * h)
        return result * h

    @staticmethod
    def simpsons_rule(f: Callable[[float], float], a: float, b: float, n: int) -> float:
        """Numerical integration using Simpson's rule."""
        if n % 2 != 0:
            n += 1
        h = (b - a) / n
        result = f(a) + f(b)

        for i in range(1, n):
            x = a + i * h
            if i % 2 == 0:
                result += 2 * f(x)
            else:
                result += 4 * f(x)

        return result * h / 3

    @staticmethod
    def gaussian_quadrature(f: Callable[[float], float], a: float, b: float,
                           n: int = 5) -> float:
        """Numerical integration using Gaussian quadrature."""
        # Legendre-Gauss nodes and weights for n=5
        nodes = [-0.9061798459, -0.5384693101, 0.0, 0.5384693101, 0.9061798459]
        weights = [0.2369268851, 0.4786286705, 0.5688888889, 0.4786286705, 0.2369268851]

        # Transform from [-1, 1] to [a, b]
        mid = (b + a) / 2
        half_length = (b - a) / 2

        result = 0.0
        for node, weight in zip(nodes, weights):
            x = mid + half_length * node
            result += weight * f(x)

        return result * half_length

    @staticmethod
    def romberg_integration(f: Callable[[float], float], a: float, b: float,
                           max_iter: int = 10, tol: float = 1e-10) -> float:
        """Romberg integration for higher accuracy."""
        R = [[0.0] * max_iter for _ in range(max_iter)]

        h = b - a
        R[0][0] = 0.5 * h * (f(a) + f(b))

        for i in range(1, max_iter):
            h /= 2
            # Trapezoidal approximation
            total = sum(f(a + (2 * k - 1) * h) for k in range(1, 2 ** (i - 1) + 1))
            R[i][0] = 0.5 * R[i - 1][0] + h * total

            # Richardson extrapolation
            for j in range(1, i + 1):
                factor = 4 ** j
                R[i][j] = (factor * R[i][j - 1] - R[i - 1][j - 1]) / (factor - 1)

            if i > 0 and abs(R[i][i] - R[i - 1][i - 1]) < tol:
                return R[i][i]

        return R[max_iter - 1][max_iter - 1]

    @staticmethod
    def monte_carlo_integration(f: Callable[[float], float], a: float, b: float,
                               n_samples: int = 10000) -> Tuple[float, float]:
        """Monte Carlo integration with error estimate."""
        samples = [f(random.uniform(a, b)) for _ in range(n_samples)]
        mean = sum(samples) / n_samples
        variance = sum((x - mean) ** 2 for x in samples) / (n_samples - 1)

        integral = (b - a) * mean
        error = (b - a) * math.sqrt(variance / n_samples)

        return integral, error


# =============================================================================
# SECTION 3: ROOT FINDING ALGORITHMS
# =============================================================================

class RootFinding:
    """Collection of root-finding algorithms."""

    @staticmethod
    def bisection(f: Callable[[float], float], a: float, b: float,
                 tol: float = 1e-10, max_iter: int = 100) -> Tuple[float, int]:
        """Find root using bisection method."""
        if f(a) * f(b) > 0:
            raise ValueError("Function must have different signs at endpoints")

        for i in range(max_iter):
            c = (a + b) / 2
            if abs(f(c)) < tol or (b - a) / 2 < tol:
                return c, i + 1

            if f(c) * f(a) < 0:
                b = c
            else:
                a = c

        return (a + b) / 2, max_iter

    @staticmethod
    def newton_raphson(f: Callable[[float], float], x0: float,
                      tol: float = 1e-10, max_iter: int = 100) -> Tuple[float, int]:
        """Find root using Newton-Raphson method."""
        x = x0
        for i in range(max_iter):
            fx = f(x)
            if abs(fx) < tol:
                return x, i + 1

            fpx = NumericalMethods.derivative(f, x)
            if abs(fpx) < 1e-15:
                raise ValueError("Derivative too small, method may not converge")

            x_new = x - fx / fpx
            if abs(x_new - x) < tol:
                return x_new, i + 1
            x = x_new

        return x, max_iter

    @staticmethod
    def secant_method(f: Callable[[float], float], x0: float, x1: float,
                     tol: float = 1e-10, max_iter: int = 100) -> Tuple[float, int]:
        """Find root using secant method."""
        for i in range(max_iter):
            f0, f1 = f(x0), f(x1)

            if abs(f1) < tol:
                return x1, i + 1

            if abs(f1 - f0) < 1e-15:
                raise ValueError("Function values too close, method may not converge")

            x2 = x1 - f1 * (x1 - x0) / (f1 - f0)

            if abs(x2 - x1) < tol:
                return x2, i + 1

            x0, x1 = x1, x2

        return x1, max_iter

    @staticmethod
    def brent_method(f: Callable[[float], float], a: float, b: float,
                    tol: float = 1e-10, max_iter: int = 100) -> Tuple[float, int]:
        """Find root using Brent's method (combines bisection, secant, and inverse quadratic)."""
        fa, fb = f(a), f(b)

        if fa * fb > 0:
            raise ValueError("Function must have different signs at endpoints")

        if abs(fa) < abs(fb):
            a, b = b, a
            fa, fb = fb, fa

        c, fc = a, fa
        d = b - a
        e = d

        for i in range(max_iter):
            if abs(fb) < tol:
                return b, i + 1

            if fa != fc and fb != fc:
                # Inverse quadratic interpolation
                s = (a * fb * fc / ((fa - fb) * (fa - fc)) +
                     b * fa * fc / ((fb - fa) * (fb - fc)) +
                     c * fa * fb / ((fc - fa) * (fc - fb)))
            else:
                # Secant method
                s = b - fb * (b - a) / (fb - fa)

            # Conditions for accepting s
            cond1 = (s - (3 * a + b) / 4) * (s - b) >= 0
            cond2 = abs(s - b) >= abs(d) / 2
            cond3 = abs(d) < tol

            if cond1 or cond2 or cond3:
                # Bisection
                s = (a + b) / 2
                d = b - a
                e = d
            else:
                d = e
                e = b - s

            a, fa = b, fb

            if abs(e) > tol:
                b = s
            else:
                b = b + tol if a < b else b - tol

            fb = f(b)

            if fb * fc > 0:
                c, fc = a, fa

        return b, max_iter

    @staticmethod
    def fixed_point_iteration(g: Callable[[float], float], x0: float,
                             tol: float = 1e-10, max_iter: int = 100) -> Tuple[float, int]:
        """Find fixed point where x = g(x)."""
        x = x0
        for i in range(max_iter):
            x_new = g(x)
            if abs(x_new - x) < tol:
                return x_new, i + 1
            x = x_new
        return x, max_iter


# =============================================================================
# SECTION 4: OPTIMIZATION ALGORITHMS
# =============================================================================

class Optimization:
    """Collection of optimization algorithms."""

    @staticmethod
    def golden_section_search(f: Callable[[float], float], a: float, b: float,
                             tol: float = 1e-10, maximize: bool = False) -> Tuple[float, float]:
        """Find minimum (or maximum) using golden section search."""
        phi = (1 + math.sqrt(5)) / 2

        if maximize:
            f = lambda x, orig=f: -orig(x)

        c = b - (b - a) / phi
        d = a + (b - a) / phi

        while abs(b - a) > tol:
            if f(c) < f(d):
                b = d
            else:
                a = c

            c = b - (b - a) / phi
            d = a + (b - a) / phi

        x_opt = (a + b) / 2
        return x_opt, f(x_opt) * (-1 if maximize else 1)

    @staticmethod
    def gradient_descent(f: Callable[..., float], x0: List[float],
                        learning_rate: float = 0.01, tol: float = 1e-8,
                        max_iter: int = 10000) -> Tuple[List[float], float, int]:
        """Minimize function using gradient descent."""
        x = x0.copy()

        for i in range(max_iter):
            grad = NumericalMethods.gradient(f, x)

            # Check convergence
            grad_norm = math.sqrt(sum(g * g for g in grad))
            if grad_norm < tol:
                return x, f(*x), i + 1

            # Update
            x = [x[j] - learning_rate * grad[j] for j in range(len(x))]

        return x, f(*x), max_iter

    @staticmethod
    def momentum_gradient_descent(f: Callable[..., float], x0: List[float],
                                  learning_rate: float = 0.01, momentum: float = 0.9,
                                  tol: float = 1e-8, max_iter: int = 10000) -> Tuple[List[float], float, int]:
        """Gradient descent with momentum."""
        x = x0.copy()
        v = [0.0] * len(x)

        for i in range(max_iter):
            grad = NumericalMethods.gradient(f, x)

            grad_norm = math.sqrt(sum(g * g for g in grad))
            if grad_norm < tol:
                return x, f(*x), i + 1

            # Update velocity and position
            for j in range(len(x)):
                v[j] = momentum * v[j] - learning_rate * grad[j]
                x[j] += v[j]

        return x, f(*x), max_iter

    @staticmethod
    def adam_optimizer(f: Callable[..., float], x0: List[float],
                      learning_rate: float = 0.001, beta1: float = 0.9,
                      beta2: float = 0.999, epsilon: float = 1e-8,
                      tol: float = 1e-8, max_iter: int = 10000) -> Tuple[List[float], float, int]:
        """Adam optimizer for gradient descent."""
        x = x0.copy()
        m = [0.0] * len(x)  # First moment
        v = [0.0] * len(x)  # Second moment

        for i in range(1, max_iter + 1):
            grad = NumericalMethods.gradient(f, x)

            grad_norm = math.sqrt(sum(g * g for g in grad))
            if grad_norm < tol:
                return x, f(*x), i

            for j in range(len(x)):
                m[j] = beta1 * m[j] + (1 - beta1) * grad[j]
                v[j] = beta2 * v[j] + (1 - beta2) * grad[j] ** 2

                m_hat = m[j] / (1 - beta1 ** i)
                v_hat = v[j] / (1 - beta2 ** i)

                x[j] -= learning_rate * m_hat / (math.sqrt(v_hat) + epsilon)

        return x, f(*x), max_iter

    @staticmethod
    def nelder_mead(f: Callable[..., float], x0: List[float],
                   alpha: float = 1.0, gamma: float = 2.0,
                   rho: float = 0.5, sigma: float = 0.5,
                   tol: float = 1e-8, max_iter: int = 10000) -> Tuple[List[float], float, int]:
        """Nelder-Mead simplex optimization."""
        n = len(x0)

        # Initialize simplex
        simplex = [x0.copy()]
        for i in range(n):
            point = x0.copy()
            point[i] += 1.0
            simplex.append(point)

        for iteration in range(max_iter):
            # Sort by function values
            simplex.sort(key=lambda x: f(*x))

            # Check convergence
            values = [f(*p) for p in simplex]
            if max(values) - min(values) < tol:
                return simplex[0], f(*simplex[0]), iteration + 1

            # Centroid (excluding worst point)
            centroid = [sum(simplex[j][i] for j in range(n)) / n for i in range(n)]

            # Reflection
            reflected = [centroid[i] + alpha * (centroid[i] - simplex[-1][i]) for i in range(n)]
            f_reflected = f(*reflected)

            if f(*simplex[0]) <= f_reflected < f(*simplex[-2]):
                simplex[-1] = reflected
                continue

            # Expansion
            if f_reflected < f(*simplex[0]):
                expanded = [centroid[i] + gamma * (reflected[i] - centroid[i]) for i in range(n)]
                if f(*expanded) < f_reflected:
                    simplex[-1] = expanded
                else:
                    simplex[-1] = reflected
                continue

            # Contraction
            contracted = [centroid[i] + rho * (simplex[-1][i] - centroid[i]) for i in range(n)]
            if f(*contracted) < f(*simplex[-1]):
                simplex[-1] = contracted
                continue

            # Shrink
            best = simplex[0]
            for i in range(1, n + 1):
                simplex[i] = [best[j] + sigma * (simplex[i][j] - best[j]) for j in range(n)]

        return simplex[0], f(*simplex[0]), max_iter

    @staticmethod
    def simulated_annealing(f: Callable[..., float], x0: List[float],
                           temp_initial: float = 100.0, temp_final: float = 0.01,
                           cooling_rate: float = 0.99, max_iter: int = 10000) -> Tuple[List[float], float, int]:
        """Simulated annealing optimization."""
        x = x0.copy()
        best_x = x.copy()
        current_cost = f(*x)
        best_cost = current_cost
        temp = temp_initial

        for i in range(max_iter):
            if temp < temp_final:
                break

            # Generate neighbor
            neighbor = [xi + random.gauss(0, temp * 0.1) for xi in x]
            neighbor_cost = f(*neighbor)

            # Accept or reject
            delta = neighbor_cost - current_cost
            if delta < 0 or random.random() < math.exp(-delta / temp):
                x = neighbor
                current_cost = neighbor_cost

                if current_cost < best_cost:
                    best_x = x.copy()
                    best_cost = current_cost

            temp *= cooling_rate

        return best_x, best_cost, i + 1


# =============================================================================
# SECTION 5: DIFFERENTIAL EQUATIONS
# =============================================================================

class DifferentialEquations:
    """Numerical methods for solving differential equations."""

    @staticmethod
    def euler_method(f: Callable[[float, float], float], y0: float,
                    t_span: Tuple[float, float], n_steps: int) -> Tuple[List[float], List[float]]:
        """Solve ODE using Euler's method."""
        t0, tf = t_span
        h = (tf - t0) / n_steps

        t_values = [t0 + i * h for i in range(n_steps + 1)]
        y_values = [y0]

        y = y0
        for i in range(n_steps):
            y = y + h * f(t_values[i], y)
            y_values.append(y)

        return t_values, y_values

    @staticmethod
    def runge_kutta_4(f: Callable[[float, float], float], y0: float,
                     t_span: Tuple[float, float], n_steps: int) -> Tuple[List[float], List[float]]:
        """Solve ODE using 4th order Runge-Kutta method."""
        t0, tf = t_span
        h = (tf - t0) / n_steps

        t_values = [t0 + i * h for i in range(n_steps + 1)]
        y_values = [y0]

        y = y0
        for i in range(n_steps):
            t = t_values[i]
            k1 = h * f(t, y)
            k2 = h * f(t + h/2, y + k1/2)
            k3 = h * f(t + h/2, y + k2/2)
            k4 = h * f(t + h, y + k3)

            y = y + (k1 + 2*k2 + 2*k3 + k4) / 6
            y_values.append(y)

        return t_values, y_values

    @staticmethod
    def runge_kutta_fehlberg(f: Callable[[float, float], float], y0: float,
                            t_span: Tuple[float, float], tol: float = 1e-6,
                            h_init: float = 0.1) -> Tuple[List[float], List[float]]:
        """Adaptive Runge-Kutta-Fehlberg method (RK45)."""
        t0, tf = t_span
        t_values = [t0]
        y_values = [y0]

        t = t0
        y = y0
        h = h_init

        while t < tf:
            if t + h > tf:
                h = tf - t

            k1 = h * f(t, y)
            k2 = h * f(t + h/4, y + k1/4)
            k3 = h * f(t + 3*h/8, y + 3*k1/32 + 9*k2/32)
            k4 = h * f(t + 12*h/13, y + 1932*k1/2197 - 7200*k2/2197 + 7296*k3/2197)
            k5 = h * f(t + h, y + 439*k1/216 - 8*k2 + 3680*k3/513 - 845*k4/4104)
            k6 = h * f(t + h/2, y - 8*k1/27 + 2*k2 - 3544*k3/2565 + 1859*k4/4104 - 11*k5/40)

            # 4th order solution
            y4 = y + 25*k1/216 + 1408*k3/2565 + 2197*k4/4104 - k5/5

            # 5th order solution
            y5 = y + 16*k1/135 + 6656*k3/12825 + 28561*k4/56430 - 9*k5/50 + 2*k6/55

            # Error estimate
            error = abs(y5 - y4)

            if error < tol or h < 1e-10:
                t += h
                y = y5
                t_values.append(t)
                y_values.append(y)

            # Adjust step size
            if error > 0:
                h = 0.9 * h * (tol / error) ** 0.2
            h = min(h, tf - t)

        return t_values, y_values

    @staticmethod
    def solve_system_rk4(f: Callable[[float, List[float]], List[float]], y0: List[float],
                        t_span: Tuple[float, float], n_steps: int) -> Tuple[List[float], List[List[float]]]:
        """Solve system of ODEs using RK4."""
        t0, tf = t_span
        h = (tf - t0) / n_steps
        n = len(y0)

        t_values = [t0 + i * h for i in range(n_steps + 1)]
        y_values = [y0]

        y = y0.copy()
        for i in range(n_steps):
            t = t_values[i]

            k1 = [h * fi for fi in f(t, y)]
            k2 = [h * fi for fi in f(t + h/2, [y[j] + k1[j]/2 for j in range(n)])]
            k3 = [h * fi for fi in f(t + h/2, [y[j] + k2[j]/2 for j in range(n)])]
            k4 = [h * fi for fi in f(t + h, [y[j] + k3[j] for j in range(n)])]

            y = [y[j] + (k1[j] + 2*k2[j] + 2*k3[j] + k4[j]) / 6 for j in range(n)]
            y_values.append(y)

        return t_values, y_values

    @staticmethod
    def boundary_value_shooting(f: Callable[[float, List[float]], List[float]],
                               t_span: Tuple[float, float], ya: float, yb: float,
                               n_steps: int = 100, tol: float = 1e-6) -> Tuple[List[float], List[float]]:
        """Solve boundary value problem using shooting method."""
        def residual(slope: float) -> float:
            y0 = [ya, slope]
            _, y_vals = DifferentialEquations.solve_system_rk4(f, y0, t_span, n_steps)
            return y_vals[-1][0] - yb

        # Find root of residual
        slope, _ = RootFinding.brent_method(residual, -10.0, 10.0, tol)

        y0 = [ya, slope]
        t_vals, y_vals = DifferentialEquations.solve_system_rk4(f, y0, t_span, n_steps)

        return t_vals, [y[0] for y in y_vals]


# =============================================================================
# SECTION 6: INTERPOLATION AND CURVE FITTING
# =============================================================================

class Interpolation:
    """Various interpolation methods."""

    @staticmethod
    def lagrange_interpolation(x_points: List[float], y_points: List[float], x: float) -> float:
        """Lagrange polynomial interpolation."""
        n = len(x_points)
        result = 0.0

        for i in range(n):
            term = y_points[i]
            for j in range(n):
                if i != j:
                    term *= (x - x_points[j]) / (x_points[i] - x_points[j])
            result += term

        return result

    @staticmethod
    def newton_interpolation(x_points: List[float], y_points: List[float], x: float) -> float:
        """Newton's divided difference interpolation."""
        n = len(x_points)

        # Calculate divided differences
        coefs = y_points.copy()
        for j in range(1, n):
            for i in range(n - 1, j - 1, -1):
                coefs[i] = (coefs[i] - coefs[i - 1]) / (x_points[i] - x_points[i - j])

        # Evaluate polynomial
        result = coefs[-1]
        for i in range(n - 2, -1, -1):
            result = result * (x - x_points[i]) + coefs[i]

        return result

    @staticmethod
    def cubic_spline(x_points: List[float], y_points: List[float]) -> Callable[[float], float]:
        """Natural cubic spline interpolation."""
        n = len(x_points)

        # Calculate second derivatives
        h = [x_points[i + 1] - x_points[i] for i in range(n - 1)]

        # Build tridiagonal system
        alpha = [0.0] * n
        for i in range(1, n - 1):
            alpha[i] = (3 * (y_points[i + 1] - y_points[i]) / h[i] -
                       3 * (y_points[i] - y_points[i - 1]) / h[i - 1])

        # Solve tridiagonal system
        l = [1.0] + [0.0] * (n - 1)
        mu = [0.0] * n
        z = [0.0] * n

        for i in range(1, n - 1):
            l[i] = 2 * (x_points[i + 1] - x_points[i - 1]) - h[i - 1] * mu[i - 1]
            mu[i] = h[i] / l[i]
            z[i] = (alpha[i] - h[i - 1] * z[i - 1]) / l[i]

        l[n - 1] = 1.0
        c = [0.0] * n
        b = [0.0] * (n - 1)
        d = [0.0] * (n - 1)

        for j in range(n - 2, -1, -1):
            c[j] = z[j] - mu[j] * c[j + 1]
            b[j] = (y_points[j + 1] - y_points[j]) / h[j] - h[j] * (c[j + 1] + 2 * c[j]) / 3
            d[j] = (c[j + 1] - c[j]) / (3 * h[j])

        def spline(x: float) -> float:
            # Find interval
            for i in range(n - 1):
                if x_points[i] <= x <= x_points[i + 1]:
                    dx = x - x_points[i]
                    return y_points[i] + b[i] * dx + c[i] * dx**2 + d[i] * dx**3

            # Extrapolation
            if x < x_points[0]:
                i = 0
            else:
                i = n - 2
            dx = x - x_points[i]
            return y_points[i] + b[i] * dx + c[i] * dx**2 + d[i] * dx**3

        return spline

    @staticmethod
    def least_squares_polynomial(x_points: List[float], y_points: List[float],
                                degree: int) -> List[float]:
        """Fit polynomial using least squares."""
        n = len(x_points)
        m = degree + 1

        # Build Vandermonde matrix
        A = Matrix([[x_points[i] ** j for j in range(m)] for i in range(n)])
        b = [[y_points[i]] for i in range(n)]
        b_matrix = Matrix(b)

        # Normal equations: A^T A c = A^T b
        AtA = A.transpose() * A
        Atb = A.transpose() * b_matrix

        # Solve using inverse (for small systems)
        coeffs = AtA.inverse() * Atb

        return [coeffs.data[i][0] for i in range(m)]

    @staticmethod
    def exponential_fit(x_points: List[float], y_points: List[float]) -> Tuple[float, float]:
        """Fit y = a * exp(b * x) using linearization."""
        # Take log: ln(y) = ln(a) + b*x
        ln_y = [math.log(y) if y > 0 else float('-inf') for y in y_points]

        # Filter out invalid points
        valid = [(x, ly) for x, ly in zip(x_points, ln_y) if math.isfinite(ly)]
        x_valid = [p[0] for p in valid]
        ln_y_valid = [p[1] for p in valid]

        # Linear regression
        n = len(x_valid)
        sum_x = sum(x_valid)
        sum_y = sum(ln_y_valid)
        sum_xy = sum(x * y for x, y in zip(x_valid, ln_y_valid))
        sum_x2 = sum(x * x for x in x_valid)

        b = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        ln_a = (sum_y - b * sum_x) / n
        a = math.exp(ln_a)

        return a, b


# =============================================================================
# SECTION 7: STATISTICS AND PROBABILITY
# =============================================================================

class Statistics:
    """Statistical functions and probability distributions."""

    @staticmethod
    def mean(data: List[float]) -> float:
        """Calculate arithmetic mean."""
        return sum(data) / len(data)

    @staticmethod
    def geometric_mean(data: List[float]) -> float:
        """Calculate geometric mean."""
        product = functools.reduce(lambda x, y: x * y, data)
        return product ** (1 / len(data))

    @staticmethod
    def harmonic_mean(data: List[float]) -> float:
        """Calculate harmonic mean."""
        return len(data) / sum(1 / x for x in data)

    @staticmethod
    def variance(data: List[float], ddof: int = 0) -> float:
        """Calculate variance."""
        m = Statistics.mean(data)
        return sum((x - m) ** 2 for x in data) / (len(data) - ddof)

    @staticmethod
    def std_dev(data: List[float], ddof: int = 0) -> float:
        """Calculate standard deviation."""
        return math.sqrt(Statistics.variance(data, ddof))

    @staticmethod
    def median(data: List[float]) -> float:
        """Calculate median."""
        sorted_data = sorted(data)
        n = len(sorted_data)
        if n % 2 == 0:
            return (sorted_data[n // 2 - 1] + sorted_data[n // 2]) / 2
        return sorted_data[n // 2]

    @staticmethod
    def percentile(data: List[float], p: float) -> float:
        """Calculate percentile."""
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * p / 100
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)

    @staticmethod
    def covariance(x: List[float], y: List[float]) -> float:
        """Calculate covariance between two variables."""
        if len(x) != len(y):
            raise ValueError("Lists must have same length")

        mx, my = Statistics.mean(x), Statistics.mean(y)
        return sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / len(x)

    @staticmethod
    def correlation(x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        cov = Statistics.covariance(x, y)
        sx, sy = Statistics.std_dev(x), Statistics.std_dev(y)
        return cov / (sx * sy)

    @staticmethod
    def linear_regression(x: List[float], y: List[float]) -> Tuple[float, float, float]:
        """Simple linear regression returning slope, intercept, and R-squared."""
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        intercept = (sum_y - slope * sum_x) / n

        # Calculate R-squared
        y_mean = sum_y / n
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        return slope, intercept, r_squared

    @staticmethod
    def skewness(data: List[float]) -> float:
        """Calculate skewness."""
        n = len(data)
        m = Statistics.mean(data)
        s = Statistics.std_dev(data, ddof=1)
        return sum(((x - m) / s) ** 3 for x in data) * n / ((n - 1) * (n - 2))

    @staticmethod
    def kurtosis(data: List[float]) -> float:
        """Calculate excess kurtosis."""
        n = len(data)
        m = Statistics.mean(data)
        s = Statistics.std_dev(data, ddof=1)
        k = sum(((x - m) / s) ** 4 for x in data)
        return k * n * (n + 1) / ((n - 1) * (n - 2) * (n - 3)) - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))

    @staticmethod
    def normal_pdf(x: float, mu: float = 0, sigma: float = 1) -> float:
        """Normal probability density function."""
        return math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))

    @staticmethod
    def normal_cdf(x: float, mu: float = 0, sigma: float = 1) -> float:
        """Normal cumulative distribution function using error function."""
        return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    @staticmethod
    def chi_squared_pdf(x: float, k: int) -> float:
        """Chi-squared probability density function."""
        if x < 0:
            return 0.0
        return (x ** (k / 2 - 1) * math.exp(-x / 2)) / (2 ** (k / 2) * math.gamma(k / 2))


# =============================================================================
# SECTION 8: SIGNAL PROCESSING
# =============================================================================

class SignalProcessing:
    """Signal processing and Fourier analysis."""

    @staticmethod
    def dft(signal: List[complex]) -> List[complex]:
        """Discrete Fourier Transform."""
        N = len(signal)
        result = []
        for k in range(N):
            total = 0j
            for n in range(N):
                angle = -2 * math.pi * k * n / N
                total += signal[n] * cmath.exp(1j * angle)
            result.append(total)
        return result

    @staticmethod
    def idft(spectrum: List[complex]) -> List[complex]:
        """Inverse Discrete Fourier Transform."""
        N = len(spectrum)
        result = []
        for n in range(N):
            total = 0j
            for k in range(N):
                angle = 2 * math.pi * k * n / N
                total += spectrum[k] * cmath.exp(1j * angle)
            result.append(total / N)
        return result

    @staticmethod
    def fft(signal: List[complex]) -> List[complex]:
        """Fast Fourier Transform using Cooley-Tukey algorithm."""
        N = len(signal)

        if N <= 1:
            return signal

        if N & (N - 1) != 0:
            # Pad to next power of 2
            next_pow2 = 1 << (N - 1).bit_length()
            signal = signal + [0j] * (next_pow2 - N)
            N = next_pow2

        if N <= 1:
            return signal

        # Divide
        even = SignalProcessing.fft(signal[0::2])
        odd = SignalProcessing.fft(signal[1::2])

        # Combine
        result = [0j] * N
        for k in range(N // 2):
            t = cmath.exp(-2j * math.pi * k / N) * odd[k]
            result[k] = even[k] + t
            result[k + N // 2] = even[k] - t

        return result

    @staticmethod
    def ifft(spectrum: List[complex]) -> List[complex]:
        """Inverse Fast Fourier Transform."""
        N = len(spectrum)

        # Conjugate, apply FFT, conjugate again, and scale
        conjugated = [x.conjugate() for x in spectrum]
        transformed = SignalProcessing.fft(conjugated)
        result = [x.conjugate() / N for x in transformed]

        return result

    @staticmethod
    def power_spectrum(signal: List[complex]) -> List[float]:
        """Calculate power spectrum of signal."""
        spectrum = SignalProcessing.fft(signal)
        return [abs(x) ** 2 for x in spectrum]

    @staticmethod
    def convolution(signal1: List[float], signal2: List[float]) -> List[float]:
        """Convolve two signals using FFT."""
        n = len(signal1) + len(signal2) - 1
        # Pad to power of 2
        fft_size = 1 << (n - 1).bit_length()

        s1 = [complex(x) for x in signal1] + [0j] * (fft_size - len(signal1))
        s2 = [complex(x) for x in signal2] + [0j] * (fft_size - len(signal2))

        fft1 = SignalProcessing.fft(s1)
        fft2 = SignalProcessing.fft(s2)

        product = [a * b for a, b in zip(fft1, fft2)]
        result = SignalProcessing.ifft(product)

        return [x.real for x in result[:n]]

    @staticmethod
    def moving_average(signal: List[float], window_size: int) -> List[float]:
        """Calculate moving average."""
        result = []
        for i in range(len(signal)):
            start = max(0, i - window_size // 2)
            end = min(len(signal), i + window_size // 2 + 1)
            result.append(sum(signal[start:end]) / (end - start))
        return result

    @staticmethod
    def low_pass_filter(signal: List[float], cutoff_ratio: float) -> List[float]:
        """Apply low-pass filter in frequency domain."""
        n = len(signal)
        spectrum = SignalProcessing.fft([complex(x) for x in signal])

        cutoff = int(n * cutoff_ratio)
        for i in range(cutoff, n - cutoff):
            spectrum[i] = 0j

        filtered = SignalProcessing.ifft(spectrum)
        return [x.real for x in filtered[:n]]

    @staticmethod
    def high_pass_filter(signal: List[float], cutoff_ratio: float) -> List[float]:
        """Apply high-pass filter in frequency domain."""
        n = len(signal)
        spectrum = SignalProcessing.fft([complex(x) for x in signal])

        cutoff = int(n * cutoff_ratio)
        for i in range(cutoff):
            spectrum[i] = 0j
            spectrum[n - 1 - i] = 0j

        filtered = SignalProcessing.ifft(spectrum)
        return [x.real for x in filtered[:n]]


# =============================================================================
# SECTION 9: COMPLEX NUMBER OPERATIONS
# =============================================================================

class ComplexMath:
    """Extended complex number operations."""

    @staticmethod
    def mandelbrot_iterations(c: complex, max_iter: int = 100) -> int:
        """Count iterations for Mandelbrot set."""
        z = 0j
        for i in range(max_iter):
            if abs(z) > 2:
                return i
            z = z * z + c
        return max_iter

    @staticmethod
    def julia_iterations(z: complex, c: complex, max_iter: int = 100) -> int:
        """Count iterations for Julia set."""
        for i in range(max_iter):
            if abs(z) > 2:
                return i
            z = z * z + c
        return max_iter

    @staticmethod
    def complex_roots_of_unity(n: int) -> List[complex]:
        """Calculate n-th roots of unity."""
        return [cmath.exp(2j * math.pi * k / n) for k in range(n)]

    @staticmethod
    def complex_logarithm(z: complex, branch: int = 0) -> complex:
        """Complex logarithm with branch selection."""
        return cmath.log(abs(z)) + 1j * (cmath.phase(z) + 2 * math.pi * branch)

    @staticmethod
    def complex_power(base: complex, exponent: complex) -> complex:
        """Calculate complex power using principal branch."""
        if base == 0:
            return 0 if exponent.real > 0 else complex(float('inf'))
        return cmath.exp(exponent * cmath.log(base))

    @staticmethod
    def residue_at_pole(f: Callable[[complex], complex], pole: complex,
                       radius: float = 0.01, n_points: int = 100) -> complex:
        """Estimate residue using contour integration."""
        result = 0j
        for k in range(n_points):
            angle = 2 * math.pi * k / n_points
            z = pole + radius * cmath.exp(1j * angle)
            dz = 1j * radius * cmath.exp(1j * angle) * 2 * math.pi / n_points
            result += f(z) * dz
        return result / (2j * math.pi)


# =============================================================================
# SECTION 10: NUMBER THEORY
# =============================================================================

class NumberTheory:
    """Number theory functions."""

    @staticmethod
    def gcd(a: int, b: int) -> int:
        """Greatest common divisor using Euclidean algorithm."""
        while b:
            a, b = b, a % b
        return abs(a)

    @staticmethod
    def lcm(a: int, b: int) -> int:
        """Least common multiple."""
        return abs(a * b) // NumberTheory.gcd(a, b)

    @staticmethod
    def extended_gcd(a: int, b: int) -> Tuple[int, int, int]:
        """Extended Euclidean algorithm returning (gcd, x, y) where ax + by = gcd."""
        if a == 0:
            return b, 0, 1

        gcd, x1, y1 = NumberTheory.extended_gcd(b % a, a)
        x = y1 - (b // a) * x1
        y = x1

        return gcd, x, y

    @staticmethod
    def mod_inverse(a: int, m: int) -> int:
        """Modular multiplicative inverse."""
        gcd, x, _ = NumberTheory.extended_gcd(a, m)
        if gcd != 1:
            raise ValueError(f"{a} has no inverse modulo {m}")
        return x % m

    @staticmethod
    def is_prime(n: int) -> bool:
        """Miller-Rabin primality test."""
        if n < 2:
            return False
        if n == 2:
            return True
        if n % 2 == 0:
            return False

        # Write n-1 as 2^r * d
        r, d = 0, n - 1
        while d % 2 == 0:
            r += 1
            d //= 2

        # Witnesses to test
        witnesses = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]

        for a in witnesses:
            if a >= n:
                continue

            x = pow(a, d, n)
            if x == 1 or x == n - 1:
                continue

            for _ in range(r - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                return False

        return True

    @staticmethod
    def prime_factors(n: int) -> List[Tuple[int, int]]:
        """Return prime factorization as list of (prime, exponent) tuples."""
        factors = []
        d = 2

        while d * d <= n:
            exp = 0
            while n % d == 0:
                exp += 1
                n //= d
            if exp > 0:
                factors.append((d, exp))
            d += 1

        if n > 1:
            factors.append((n, 1))

        return factors

    @staticmethod
    def euler_phi(n: int) -> int:
        """Euler's totient function."""
        result = n
        for prime, _ in NumberTheory.prime_factors(n):
            result -= result // prime
        return result

    @staticmethod
    def chinese_remainder_theorem(remainders: List[int], moduli: List[int]) -> int:
        """Solve system of congruences using CRT."""
        if len(remainders) != len(moduli):
            raise ValueError("Lists must have same length")

        M = functools.reduce(lambda x, y: x * y, moduli)
        result = 0

        for r, m in zip(remainders, moduli):
            Mi = M // m
            yi = NumberTheory.mod_inverse(Mi, m)
            result += r * Mi * yi

        return result % M

    @staticmethod
    def fibonacci(n: int) -> int:
        """Calculate n-th Fibonacci number using matrix exponentiation."""
        if n <= 0:
            return 0
        if n == 1:
            return 1

        def matrix_mult(A: List[List[int]], B: List[List[int]]) -> List[List[int]]:
            return [
                [A[0][0] * B[0][0] + A[0][1] * B[1][0],
                 A[0][0] * B[0][1] + A[0][1] * B[1][1]],
                [A[1][0] * B[0][0] + A[1][1] * B[1][0],
                 A[1][0] * B[0][1] + A[1][1] * B[1][1]]
            ]

        def matrix_pow(M: List[List[int]], p: int) -> List[List[int]]:
            if p == 1:
                return M
            if p % 2 == 0:
                half = matrix_pow(M, p // 2)
                return matrix_mult(half, half)
            return matrix_mult(M, matrix_pow(M, p - 1))

        F = [[1, 1], [1, 0]]
        result = matrix_pow(F, n)
        return result[0][1]


# =============================================================================
# MAIN: DEMONSTRATION
# =============================================================================

def run_demonstrations():
    """Run demonstrations of all calculation modules."""
    print("=" * 80)
    print("COMPLEX CALCULATIONS DEMONSTRATION")
    print("=" * 80)

    # Matrix operations
    print("\n" + "-" * 40)
    print("1. MATRIX OPERATIONS")
    print("-" * 40)

    A = Matrix([[4, 7, 2], [3, 6, 1], [2, 5, 3]])
    B = Matrix([[1, 0, 2], [0, 1, 1], [2, 1, 0]])

    print(f"Matrix A:\n{A}")
    print(f"\nMatrix B:\n{B}")
    print(f"\nA + B:\n{A + B}")
    print(f"\nA * B:\n{A * B}")
    print(f"\nDeterminant of A: {A.determinant():.6f}")
    print(f"Trace of A: {A.trace():.6f}")

    eigenval, eigenvec = A.eigenvalues_power_method()
    print(f"Dominant eigenvalue of A: {eigenval:.6f}")

    # Numerical integration
    print("\n" + "-" * 40)
    print("2. NUMERICAL INTEGRATION")
    print("-" * 40)

    f = lambda x: math.sin(x) * math.exp(-x / 10)
    a, b = 0, math.pi * 4

    trap = NumericalMethods.trapezoidal_rule(f, a, b, 1000)
    simp = NumericalMethods.simpsons_rule(f, a, b, 1000)
    gauss = NumericalMethods.gaussian_quadrature(f, a, b)
    romb = NumericalMethods.romberg_integration(f, a, b)
    mc, mc_err = NumericalMethods.monte_carlo_integration(f, a, b, 50000)

    print(f"Integral of sin(x)*exp(-x/10) from 0 to 4π:")
    print(f"  Trapezoidal rule: {trap:.10f}")
    print(f"  Simpson's rule:   {simp:.10f}")
    print(f"  Gaussian quad:    {gauss:.10f}")
    print(f"  Romberg:          {romb:.10f}")
    print(f"  Monte Carlo:      {mc:.10f} ± {mc_err:.10f}")

    # Root finding
    print("\n" + "-" * 40)
    print("3. ROOT FINDING")
    print("-" * 40)

    g = lambda x: x**3 - 2*x - 5

    root_bis, iter_bis = RootFinding.bisection(g, 2, 3)
    root_nr, iter_nr = RootFinding.newton_raphson(g, 2.5)
    root_sec, iter_sec = RootFinding.secant_method(g, 2, 3)
    root_br, iter_br = RootFinding.brent_method(g, 2, 3)

    print(f"Root of x³ - 2x - 5 = 0:")
    print(f"  Bisection:      {root_bis:.12f} ({iter_bis} iterations)")
    print(f"  Newton-Raphson: {root_nr:.12f} ({iter_nr} iterations)")
    print(f"  Secant:         {root_sec:.12f} ({iter_sec} iterations)")
    print(f"  Brent:          {root_br:.12f} ({iter_br} iterations)")

    # Optimization
    print("\n" + "-" * 40)
    print("4. OPTIMIZATION")
    print("-" * 40)

    rosenbrock = lambda x, y: (1 - x)**2 + 100 * (y - x**2)**2

    x_gd, f_gd, i_gd = Optimization.gradient_descent(rosenbrock, [-1.0, -1.0],
                                                      learning_rate=0.001, max_iter=50000)
    x_adam, f_adam, i_adam = Optimization.adam_optimizer(rosenbrock, [-1.0, -1.0],
                                                          max_iter=50000)
    x_nm, f_nm, i_nm = Optimization.nelder_mead(rosenbrock, [-1.0, -1.0])
    x_sa, f_sa, i_sa = Optimization.simulated_annealing(rosenbrock, [-1.0, -1.0])

    print(f"Minimizing Rosenbrock function (minimum at (1, 1)):")
    print(f"  Gradient descent: x=({x_gd[0]:.6f}, {x_gd[1]:.6f}), f={f_gd:.6e}")
    print(f"  Adam optimizer:   x=({x_adam[0]:.6f}, {x_adam[1]:.6f}), f={f_adam:.6e}")
    print(f"  Nelder-Mead:      x=({x_nm[0]:.6f}, {x_nm[1]:.6f}), f={f_nm:.6e}")
    print(f"  Sim. annealing:   x=({x_sa[0]:.6f}, {x_sa[1]:.6f}), f={f_sa:.6e}")

    # Differential equations
    print("\n" + "-" * 40)
    print("5. DIFFERENTIAL EQUATIONS")
    print("-" * 40)

    # dy/dt = -2y (solution: y = e^(-2t))
    ode = lambda t, y: -2 * y
    t_span = (0, 2)
    y0 = 1.0

    t_euler, y_euler = DifferentialEquations.euler_method(ode, y0, t_span, 100)
    t_rk4, y_rk4 = DifferentialEquations.runge_kutta_4(ode, y0, t_span, 100)
    t_rkf, y_rkf = DifferentialEquations.runge_kutta_fehlberg(ode, y0, t_span)

    exact_final = math.exp(-4)
    print(f"Solving dy/dt = -2y, y(0) = 1:")
    print(f"  Exact y(2) = e^(-4) = {exact_final:.10f}")
    print(f"  Euler:  y(2) = {y_euler[-1]:.10f}, error = {abs(y_euler[-1] - exact_final):.2e}")
    print(f"  RK4:    y(2) = {y_rk4[-1]:.10f}, error = {abs(y_rk4[-1] - exact_final):.2e}")
    print(f"  RK45:   y(2) = {y_rkf[-1]:.10f}, error = {abs(y_rkf[-1] - exact_final):.2e}")

    # Statistics
    print("\n" + "-" * 40)
    print("6. STATISTICS")
    print("-" * 40)

    data = [random.gauss(50, 10) for _ in range(1000)]

    print(f"Statistics of 1000 samples from N(50, 10):")
    print(f"  Mean:     {Statistics.mean(data):.4f}")
    print(f"  Median:   {Statistics.median(data):.4f}")
    print(f"  Std Dev:  {Statistics.std_dev(data, ddof=1):.4f}")
    print(f"  Skewness: {Statistics.skewness(data):.4f}")
    print(f"  Kurtosis: {Statistics.kurtosis(data):.4f}")

    # Signal processing
    print("\n" + "-" * 40)
    print("7. SIGNAL PROCESSING")
    print("-" * 40)

    signal = [math.sin(2 * math.pi * k / 16) + 0.5 * math.sin(6 * math.pi * k / 16)
              for k in range(64)]
    spectrum = SignalProcessing.fft([complex(x) for x in signal])
    power = SignalProcessing.power_spectrum([complex(x) for x in signal])

    print(f"FFT of composite sine wave (64 samples):")
    print(f"  DC component: {abs(spectrum[0]):.4f}")
    print(f"  Peak frequencies at bins: ", end="")
    sorted_indices = sorted(range(len(power)), key=lambda i: power[i], reverse=True)[:4]
    print(", ".join(str(i) for i in sorted_indices))

    # Number theory
    print("\n" + "-" * 40)
    print("8. NUMBER THEORY")
    print("-" * 40)

    n = 123456789
    print(f"Number theory for n = {n}:")
    print(f"  Prime factorization: {NumberTheory.prime_factors(n)}")
    print(f"  Euler's phi: {NumberTheory.euler_phi(n)}")
    print(f"  Is prime: {NumberTheory.is_prime(n)}")
    print(f"  Fibonacci(50): {NumberTheory.fibonacci(50)}")

    # CRT example
    remainders = [2, 3, 2]
    moduli = [3, 5, 7]
    crt_result = NumberTheory.chinese_remainder_theorem(remainders, moduli)
    print(f"  CRT solution for x ≡ {remainders} (mod {moduli}): x = {crt_result}")

    # Complex analysis
    print("\n" + "-" * 40)
    print("9. COMPLEX ANALYSIS")
    print("-" * 40)

    roots = ComplexMath.complex_roots_of_unity(5)
    print("5th roots of unity:")
    for i, root in enumerate(roots):
        print(f"  ω_{i} = {root.real:.6f} + {root.imag:.6f}i")

    # Mandelbrot
    c = complex(-0.7, 0.27)
    mandel_iters = ComplexMath.mandelbrot_iterations(c, 1000)
    print(f"\nMandelbrot iterations for c = {c}: {mandel_iters}")

    # Interpolation
    print("\n" + "-" * 40)
    print("10. INTERPOLATION")
    print("-" * 40)

    x_pts = [0, 1, 2, 3, 4]
    y_pts = [1, 2.7, 7.4, 20.1, 54.6]  # Approximately e^x

    x_test = 2.5
    lagrange = Interpolation.lagrange_interpolation(x_pts, y_pts, x_test)
    newton = Interpolation.newton_interpolation(x_pts, y_pts, x_test)
    spline = Interpolation.cubic_spline(x_pts, y_pts)

    print(f"Interpolating e^x at x = {x_test}:")
    print(f"  Exact:    {math.exp(x_test):.6f}")
    print(f"  Lagrange: {lagrange:.6f}")
    print(f"  Newton:   {newton:.6f}")
    print(f"  Spline:   {spline(x_test):.6f}")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_demonstrations()
