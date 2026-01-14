#!/usr/bin/env python3
"""
Complex Calculations Library
A comprehensive Python script implementing various numerical methods,
statistical analysis, linear algebra operations, signal processing,
and optimization algorithms.

Author: Claude Code
Version: 1.0.0
"""

import math
import random
import time
from typing import List, Tuple, Callable, Optional, Union, Dict, Any
from functools import reduce, lru_cache
from collections import defaultdict
import itertools


# =============================================================================
# SECTION 1: BASIC MATHEMATICAL UTILITIES
# =============================================================================

class MathUtils:
    """Collection of basic mathematical utility functions."""

    @staticmethod
    def factorial(n: int) -> int:
        """Calculate factorial of n using iterative approach."""
        if n < 0:
            raise ValueError("Factorial not defined for negative numbers")
        result = 1
        for i in range(2, n + 1):
            result *= i
        return result

    @staticmethod
    def fibonacci(n: int) -> int:
        """Calculate nth Fibonacci number using matrix exponentiation."""
        if n < 0:
            raise ValueError("Fibonacci not defined for negative indices")
        if n <= 1:
            return n

        def matrix_mult(a: List[List[int]], b: List[List[int]]) -> List[List[int]]:
            return [
                [a[0][0]*b[0][0] + a[0][1]*b[1][0], a[0][0]*b[0][1] + a[0][1]*b[1][1]],
                [a[1][0]*b[0][0] + a[1][1]*b[1][0], a[1][0]*b[0][1] + a[1][1]*b[1][1]]
            ]

        def matrix_pow(matrix: List[List[int]], power: int) -> List[List[int]]:
            result = [[1, 0], [0, 1]]
            base = [row[:] for row in matrix]
            while power > 0:
                if power % 2 == 1:
                    result = matrix_mult(result, base)
                base = matrix_mult(base, base)
                power //= 2
            return result

        fib_matrix = [[1, 1], [1, 0]]
        result_matrix = matrix_pow(fib_matrix, n)
        return result_matrix[0][1]

    @staticmethod
    def gcd(a: int, b: int) -> int:
        """Calculate GCD using Euclidean algorithm."""
        while b:
            a, b = b, a % b
        return abs(a)

    @staticmethod
    def lcm(a: int, b: int) -> int:
        """Calculate LCM using GCD."""
        return abs(a * b) // MathUtils.gcd(a, b) if a and b else 0

    @staticmethod
    def is_prime(n: int) -> bool:
        """Check if n is prime using Miller-Rabin primality test."""
        if n < 2:
            return False
        if n == 2 or n == 3:
            return True
        if n % 2 == 0:
            return False

        r, d = 0, n - 1
        while d % 2 == 0:
            r += 1
            d //= 2

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
    def prime_factors(n: int) -> List[int]:
        """Find all prime factors of n."""
        factors = []
        d = 2
        while d * d <= n:
            while n % d == 0:
                factors.append(d)
                n //= d
            d += 1
        if n > 1:
            factors.append(n)
        return factors

    @staticmethod
    def sieve_of_eratosthenes(limit: int) -> List[int]:
        """Generate all primes up to limit using Sieve of Eratosthenes."""
        if limit < 2:
            return []
        is_prime = [True] * (limit + 1)
        is_prime[0] = is_prime[1] = False
        for i in range(2, int(limit**0.5) + 1):
            if is_prime[i]:
                for j in range(i*i, limit + 1, i):
                    is_prime[j] = False
        return [i for i in range(limit + 1) if is_prime[i]]


# =============================================================================
# SECTION 2: NUMERICAL ANALYSIS AND CALCULUS
# =============================================================================

class NumericalAnalysis:
    """Numerical methods for calculus and equation solving."""

    @staticmethod
    def derivative(f: Callable[[float], float], x: float, h: float = 1e-8) -> float:
        """Calculate numerical derivative using central difference method."""
        return (f(x + h) - f(x - h)) / (2 * h)

    @staticmethod
    def second_derivative(f: Callable[[float], float], x: float, h: float = 1e-5) -> float:
        """Calculate second derivative using central difference."""
        return (f(x + h) - 2*f(x) + f(x - h)) / (h * h)

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
        return [NumericalAnalysis.partial_derivative(f, args, i, h)
                for i in range(len(args))]

    @staticmethod
    def integrate_trapezoidal(f: Callable[[float], float], a: float,
                             b: float, n: int = 1000) -> float:
        """Numerical integration using trapezoidal rule."""
        h = (b - a) / n
        result = 0.5 * (f(a) + f(b))
        for i in range(1, n):
            result += f(a + i * h)
        return result * h

    @staticmethod
    def integrate_simpson(f: Callable[[float], float], a: float,
                         b: float, n: int = 1000) -> float:
        """Numerical integration using Simpson's rule."""
        if n % 2 == 1:
            n += 1
        h = (b - a) / n
        result = f(a) + f(b)
        for i in range(1, n):
            coef = 4 if i % 2 == 1 else 2
            result += coef * f(a + i * h)
        return result * h / 3

    @staticmethod
    def integrate_romberg(f: Callable[[float], float], a: float,
                         b: float, max_iter: int = 10, tol: float = 1e-10) -> float:
        """Romberg integration for higher accuracy."""
        R = [[0.0] * (max_iter + 1) for _ in range(max_iter + 1)]
        h = b - a
        R[0][0] = 0.5 * h * (f(a) + f(b))

        for i in range(1, max_iter + 1):
            h /= 2
            sum_val = sum(f(a + (2*k - 1) * h) for k in range(1, 2**(i-1) + 1))
            R[i][0] = 0.5 * R[i-1][0] + h * sum_val

            for j in range(1, i + 1):
                R[i][j] = R[i][j-1] + (R[i][j-1] - R[i-1][j-1]) / (4**j - 1)

            if i > 1 and abs(R[i][i] - R[i-1][i-1]) < tol:
                return R[i][i]

        return R[max_iter][max_iter]

    @staticmethod
    def newton_raphson(f: Callable[[float], float], x0: float,
                      tol: float = 1e-10, max_iter: int = 100) -> float:
        """Find root using Newton-Raphson method."""
        x = x0
        for _ in range(max_iter):
            fx = f(x)
            if abs(fx) < tol:
                return x
            dfx = NumericalAnalysis.derivative(f, x)
            if abs(dfx) < 1e-15:
                raise ValueError("Derivative too small")
            x = x - fx / dfx
        raise ValueError("Newton-Raphson did not converge")

    @staticmethod
    def bisection(f: Callable[[float], float], a: float, b: float,
                 tol: float = 1e-10, max_iter: int = 100) -> float:
        """Find root using bisection method."""
        if f(a) * f(b) > 0:
            raise ValueError("Function must have opposite signs at endpoints")

        for _ in range(max_iter):
            c = (a + b) / 2
            if abs(f(c)) < tol or (b - a) / 2 < tol:
                return c
            if f(c) * f(a) < 0:
                b = c
            else:
                a = c
        return (a + b) / 2

    @staticmethod
    def secant_method(f: Callable[[float], float], x0: float, x1: float,
                     tol: float = 1e-10, max_iter: int = 100) -> float:
        """Find root using secant method."""
        for _ in range(max_iter):
            fx0, fx1 = f(x0), f(x1)
            if abs(fx1) < tol:
                return x1
            if abs(fx1 - fx0) < 1e-15:
                raise ValueError("Division by zero in secant method")
            x2 = x1 - fx1 * (x1 - x0) / (fx1 - fx0)
            x0, x1 = x1, x2
        raise ValueError("Secant method did not converge")


# =============================================================================
# SECTION 3: LINEAR ALGEBRA
# =============================================================================

class Matrix:
    """Matrix class with various linear algebra operations."""

    def __init__(self, data: List[List[float]]):
        """Initialize matrix from 2D list."""
        self.data = [row[:] for row in data]
        self.rows = len(data)
        self.cols = len(data[0]) if data else 0

    def __repr__(self) -> str:
        return f"Matrix({self.data})"

    def __str__(self) -> str:
        return '\n'.join(['\t'.join(f'{x:.4f}' for x in row) for row in self.data])

    def __getitem__(self, key: Tuple[int, int]) -> float:
        return self.data[key[0]][key[1]]

    def __setitem__(self, key: Tuple[int, int], value: float):
        self.data[key[0]][key[1]] = value

    def __add__(self, other: 'Matrix') -> 'Matrix':
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrix dimensions must match for addition")
        result = [[self.data[i][j] + other.data[i][j]
                  for j in range(self.cols)] for i in range(self.rows)]
        return Matrix(result)

    def __sub__(self, other: 'Matrix') -> 'Matrix':
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrix dimensions must match for subtraction")
        result = [[self.data[i][j] - other.data[i][j]
                  for j in range(self.cols)] for i in range(self.rows)]
        return Matrix(result)

    def __mul__(self, other: Union['Matrix', float]) -> 'Matrix':
        if isinstance(other, (int, float)):
            result = [[self.data[i][j] * other
                      for j in range(self.cols)] for i in range(self.rows)]
            return Matrix(result)
        if self.cols != other.rows:
            raise ValueError("Matrix dimensions incompatible for multiplication")
        result = [[sum(self.data[i][k] * other.data[k][j] for k in range(self.cols))
                  for j in range(other.cols)] for i in range(self.rows)]
        return Matrix(result)

    @staticmethod
    def identity(n: int) -> 'Matrix':
        """Create n x n identity matrix."""
        return Matrix([[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)])

    @staticmethod
    def zeros(rows: int, cols: int) -> 'Matrix':
        """Create matrix of zeros."""
        return Matrix([[0.0] * cols for _ in range(rows)])

    @staticmethod
    def random(rows: int, cols: int, low: float = 0, high: float = 1) -> 'Matrix':
        """Create matrix with random values."""
        return Matrix([[random.uniform(low, high) for _ in range(cols)]
                      for _ in range(rows)])

    def transpose(self) -> 'Matrix':
        """Return transpose of matrix."""
        result = [[self.data[j][i] for j in range(self.rows)] for i in range(self.cols)]
        return Matrix(result)

    def trace(self) -> float:
        """Calculate trace of square matrix."""
        if self.rows != self.cols:
            raise ValueError("Trace only defined for square matrices")
        return sum(self.data[i][i] for i in range(self.rows))

    def determinant(self) -> float:
        """Calculate determinant using LU decomposition."""
        if self.rows != self.cols:
            raise ValueError("Determinant only defined for square matrices")

        n = self.rows
        lu = [row[:] for row in self.data]
        det = 1.0

        for i in range(n):
            max_row = max(range(i, n), key=lambda r: abs(lu[r][i]))
            if abs(lu[max_row][i]) < 1e-15:
                return 0.0
            if max_row != i:
                lu[i], lu[max_row] = lu[max_row], lu[i]
                det *= -1

            det *= lu[i][i]
            for j in range(i + 1, n):
                factor = lu[j][i] / lu[i][i]
                for k in range(i, n):
                    lu[j][k] -= factor * lu[i][k]

        return det

    def inverse(self) -> 'Matrix':
        """Calculate inverse using Gauss-Jordan elimination."""
        if self.rows != self.cols:
            raise ValueError("Inverse only defined for square matrices")

        n = self.rows
        augmented = [self.data[i] + [1.0 if i == j else 0.0 for j in range(n)]
                    for i in range(n)]

        for i in range(n):
            max_row = max(range(i, n), key=lambda r: abs(augmented[r][i]))
            if abs(augmented[max_row][i]) < 1e-15:
                raise ValueError("Matrix is singular")
            augmented[i], augmented[max_row] = augmented[max_row], augmented[i]

            pivot = augmented[i][i]
            augmented[i] = [x / pivot for x in augmented[i]]

            for j in range(n):
                if i != j:
                    factor = augmented[j][i]
                    augmented[j] = [augmented[j][k] - factor * augmented[i][k]
                                   for k in range(2 * n)]

        return Matrix([row[n:] for row in augmented])

    def lu_decomposition(self) -> Tuple['Matrix', 'Matrix']:
        """Perform LU decomposition."""
        if self.rows != self.cols:
            raise ValueError("LU decomposition requires square matrix")

        n = self.rows
        L = Matrix.identity(n)
        U = Matrix([row[:] for row in self.data])

        for i in range(n):
            for j in range(i + 1, n):
                if abs(U[i, i]) < 1e-15:
                    raise ValueError("Zero pivot encountered")
                factor = U[j, i] / U[i, i]
                L[j, i] = factor
                for k in range(i, n):
                    U[j, k] -= factor * U[i, k]

        return L, U

    def qr_decomposition(self) -> Tuple['Matrix', 'Matrix']:
        """Perform QR decomposition using Gram-Schmidt process."""
        n, m = self.rows, self.cols
        Q = Matrix.zeros(n, m)
        R = Matrix.zeros(m, m)

        for j in range(m):
            v = [self.data[i][j] for i in range(n)]

            for i in range(j):
                R[i, j] = sum(Q[k, i] * self.data[k][j] for k in range(n))
                for k in range(n):
                    v[k] -= R[i, j] * Q[k, i]

            R[j, j] = math.sqrt(sum(x*x for x in v))
            if R[j, j] > 1e-15:
                for k in range(n):
                    Q[k, j] = v[k] / R[j, j]

        return Q, R

    def eigenvalues_power_iteration(self, num_iterations: int = 1000,
                                   tol: float = 1e-10) -> Tuple[float, List[float]]:
        """Find dominant eigenvalue using power iteration."""
        if self.rows != self.cols:
            raise ValueError("Eigenvalues only for square matrices")

        n = self.rows
        b = [random.random() for _ in range(n)]
        norm = math.sqrt(sum(x*x for x in b))
        b = [x/norm for x in b]

        eigenvalue = 0.0
        for _ in range(num_iterations):
            b_new = [sum(self.data[i][j] * b[j] for j in range(n)) for i in range(n)]
            norm = math.sqrt(sum(x*x for x in b_new))
            b_new = [x/norm for x in b_new]

            new_eigenvalue = sum(sum(self.data[i][j] * b_new[j] for j in range(n)) * b_new[i]
                                for i in range(n))

            if abs(new_eigenvalue - eigenvalue) < tol:
                return new_eigenvalue, b_new

            eigenvalue = new_eigenvalue
            b = b_new

        return eigenvalue, b

    def solve_linear_system(self, b: List[float]) -> List[float]:
        """Solve Ax = b using Gaussian elimination with partial pivoting."""
        if self.rows != self.cols or len(b) != self.rows:
            raise ValueError("Invalid dimensions for linear system")

        n = self.rows
        augmented = [self.data[i] + [b[i]] for i in range(n)]

        for i in range(n):
            max_row = max(range(i, n), key=lambda r: abs(augmented[r][i]))
            augmented[i], augmented[max_row] = augmented[max_row], augmented[i]

            if abs(augmented[i][i]) < 1e-15:
                raise ValueError("System has no unique solution")

            for j in range(i + 1, n):
                factor = augmented[j][i] / augmented[i][i]
                for k in range(i, n + 1):
                    augmented[j][k] -= factor * augmented[i][k]

        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            x[i] = (augmented[i][n] - sum(augmented[i][j] * x[j]
                   for j in range(i + 1, n))) / augmented[i][i]

        return x


# =============================================================================
# SECTION 4: STATISTICS AND PROBABILITY
# =============================================================================

class Statistics:
    """Statistical analysis and probability functions."""

    @staticmethod
    def mean(data: List[float]) -> float:
        """Calculate arithmetic mean."""
        if not data:
            raise ValueError("Cannot calculate mean of empty list")
        return sum(data) / len(data)

    @staticmethod
    def geometric_mean(data: List[float]) -> float:
        """Calculate geometric mean."""
        if not data or any(x <= 0 for x in data):
            raise ValueError("Geometric mean requires positive values")
        return math.exp(sum(math.log(x) for x in data) / len(data))

    @staticmethod
    def harmonic_mean(data: List[float]) -> float:
        """Calculate harmonic mean."""
        if not data or any(x <= 0 for x in data):
            raise ValueError("Harmonic mean requires positive values")
        return len(data) / sum(1/x for x in data)

    @staticmethod
    def median(data: List[float]) -> float:
        """Calculate median."""
        if not data:
            raise ValueError("Cannot calculate median of empty list")
        sorted_data = sorted(data)
        n = len(sorted_data)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_data[mid - 1] + sorted_data[mid]) / 2
        return sorted_data[mid]

    @staticmethod
    def mode(data: List[float]) -> List[float]:
        """Find mode(s) of data."""
        if not data:
            raise ValueError("Cannot find mode of empty list")
        counts = defaultdict(int)
        for x in data:
            counts[x] += 1
        max_count = max(counts.values())
        return [x for x, count in counts.items() if count == max_count]

    @staticmethod
    def variance(data: List[float], sample: bool = True) -> float:
        """Calculate variance (sample or population)."""
        if len(data) < 2:
            raise ValueError("Need at least 2 data points")
        mean = Statistics.mean(data)
        squared_diff = sum((x - mean) ** 2 for x in data)
        return squared_diff / (len(data) - 1 if sample else len(data))

    @staticmethod
    def std_dev(data: List[float], sample: bool = True) -> float:
        """Calculate standard deviation."""
        return math.sqrt(Statistics.variance(data, sample))

    @staticmethod
    def covariance(x: List[float], y: List[float], sample: bool = True) -> float:
        """Calculate covariance between two variables."""
        if len(x) != len(y) or len(x) < 2:
            raise ValueError("Invalid data for covariance")
        mean_x, mean_y = Statistics.mean(x), Statistics.mean(y)
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        return cov / (len(x) - 1 if sample else len(x))

    @staticmethod
    def correlation(x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        if len(x) != len(y) or len(x) < 2:
            raise ValueError("Invalid data for correlation")
        cov = Statistics.covariance(x, y)
        std_x, std_y = Statistics.std_dev(x), Statistics.std_dev(y)
        if std_x == 0 or std_y == 0:
            return 0.0
        return cov / (std_x * std_y)

    @staticmethod
    def percentile(data: List[float], p: float) -> float:
        """Calculate p-th percentile (0-100)."""
        if not data or not 0 <= p <= 100:
            raise ValueError("Invalid data or percentile")
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * p / 100
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    @staticmethod
    def quartiles(data: List[float]) -> Tuple[float, float, float]:
        """Calculate Q1, Q2 (median), Q3."""
        return (Statistics.percentile(data, 25),
                Statistics.percentile(data, 50),
                Statistics.percentile(data, 75))

    @staticmethod
    def iqr(data: List[float]) -> float:
        """Calculate interquartile range."""
        q1, _, q3 = Statistics.quartiles(data)
        return q3 - q1

    @staticmethod
    def skewness(data: List[float]) -> float:
        """Calculate skewness of distribution."""
        n = len(data)
        if n < 3:
            raise ValueError("Need at least 3 data points")
        mean = Statistics.mean(data)
        std = Statistics.std_dev(data, sample=False)
        if std == 0:
            return 0.0
        return sum(((x - mean) / std) ** 3 for x in data) * n / ((n-1) * (n-2))

    @staticmethod
    def kurtosis(data: List[float]) -> float:
        """Calculate excess kurtosis."""
        n = len(data)
        if n < 4:
            raise ValueError("Need at least 4 data points")
        mean = Statistics.mean(data)
        std = Statistics.std_dev(data, sample=False)
        if std == 0:
            return 0.0
        m4 = sum((x - mean) ** 4 for x in data) / n
        return m4 / (std ** 4) - 3

    @staticmethod
    def z_score(x: float, mean: float, std: float) -> float:
        """Calculate z-score."""
        if std == 0:
            raise ValueError("Standard deviation cannot be zero")
        return (x - mean) / std

    @staticmethod
    def linear_regression(x: List[float], y: List[float]) -> Tuple[float, float, float]:
        """Perform simple linear regression. Returns (slope, intercept, r_squared)."""
        if len(x) != len(y) or len(x) < 2:
            raise ValueError("Invalid data for regression")

        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)

        denom = n * sum_x2 - sum_x ** 2
        if abs(denom) < 1e-15:
            raise ValueError("Cannot perform regression on constant x")

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        y_pred = [slope * xi + intercept for xi in x]
        mean_y = sum_y / n
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)
        ss_res = sum((yi - ypi) ** 2 for yi, ypi in zip(y, y_pred))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        return slope, intercept, r_squared


# =============================================================================
# SECTION 5: PROBABILITY DISTRIBUTIONS
# =============================================================================

class Distributions:
    """Probability distribution functions."""

    @staticmethod
    def normal_pdf(x: float, mu: float = 0, sigma: float = 1) -> float:
        """Normal distribution probability density function."""
        coef = 1 / (sigma * math.sqrt(2 * math.pi))
        exponent = -0.5 * ((x - mu) / sigma) ** 2
        return coef * math.exp(exponent)

    @staticmethod
    def normal_cdf(x: float, mu: float = 0, sigma: float = 1) -> float:
        """Normal distribution cumulative distribution function."""
        return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    @staticmethod
    def binomial_pmf(k: int, n: int, p: float) -> float:
        """Binomial distribution probability mass function."""
        if not 0 <= p <= 1 or k < 0 or k > n:
            return 0.0
        coef = MathUtils.factorial(n) // (MathUtils.factorial(k) * MathUtils.factorial(n - k))
        return coef * (p ** k) * ((1 - p) ** (n - k))

    @staticmethod
    def poisson_pmf(k: int, lambda_: float) -> float:
        """Poisson distribution probability mass function."""
        if k < 0 or lambda_ < 0:
            return 0.0
        return (lambda_ ** k) * math.exp(-lambda_) / MathUtils.factorial(k)

    @staticmethod
    def exponential_pdf(x: float, lambda_: float) -> float:
        """Exponential distribution probability density function."""
        if x < 0 or lambda_ <= 0:
            return 0.0
        return lambda_ * math.exp(-lambda_ * x)

    @staticmethod
    def exponential_cdf(x: float, lambda_: float) -> float:
        """Exponential distribution cumulative distribution function."""
        if x < 0:
            return 0.0
        return 1 - math.exp(-lambda_ * x)

    @staticmethod
    def uniform_pdf(x: float, a: float, b: float) -> float:
        """Uniform distribution probability density function."""
        if a >= b:
            raise ValueError("Invalid interval")
        return 1 / (b - a) if a <= x <= b else 0.0

    @staticmethod
    def gamma_function(z: float) -> float:
        """Gamma function using Lanczos approximation."""
        if z < 0.5:
            return math.pi / (math.sin(math.pi * z) * Distributions.gamma_function(1 - z))

        z -= 1
        g = 7
        c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028,
             771.32342877765313, -176.61502916214059, 12.507343278686905,
             -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7]

        x = c[0]
        for i in range(1, g + 2):
            x += c[i] / (z + i)

        t = z + g + 0.5
        return math.sqrt(2 * math.pi) * (t ** (z + 0.5)) * math.exp(-t) * x

    @staticmethod
    def beta_function(a: float, b: float) -> float:
        """Beta function."""
        return (Distributions.gamma_function(a) * Distributions.gamma_function(b) /
                Distributions.gamma_function(a + b))

    @staticmethod
    def chi_squared_pdf(x: float, k: int) -> float:
        """Chi-squared distribution probability density function."""
        if x < 0 or k < 1:
            return 0.0
        coef = 1 / (2 ** (k/2) * Distributions.gamma_function(k/2))
        return coef * (x ** (k/2 - 1)) * math.exp(-x/2)

    @staticmethod
    def student_t_pdf(x: float, df: int) -> float:
        """Student's t-distribution probability density function."""
        coef = (Distributions.gamma_function((df + 1) / 2) /
                (math.sqrt(df * math.pi) * Distributions.gamma_function(df / 2)))
        return coef * (1 + x**2 / df) ** (-(df + 1) / 2)


# =============================================================================
# SECTION 6: SIGNAL PROCESSING
# =============================================================================

class SignalProcessing:
    """Signal processing algorithms."""

    @staticmethod
    def dft(signal: List[complex]) -> List[complex]:
        """Discrete Fourier Transform."""
        n = len(signal)
        result = []
        for k in range(n):
            total = 0j
            for t in range(n):
                angle = -2 * math.pi * k * t / n
                total += signal[t] * complex(math.cos(angle), math.sin(angle))
            result.append(total)
        return result

    @staticmethod
    def idft(spectrum: List[complex]) -> List[complex]:
        """Inverse Discrete Fourier Transform."""
        n = len(spectrum)
        result = []
        for t in range(n):
            total = 0j
            for k in range(n):
                angle = 2 * math.pi * k * t / n
                total += spectrum[k] * complex(math.cos(angle), math.sin(angle))
            result.append(total / n)
        return result

    @staticmethod
    def fft(signal: List[complex]) -> List[complex]:
        """Fast Fourier Transform using Cooley-Tukey algorithm."""
        n = len(signal)
        if n <= 1:
            return signal
        if n & (n - 1) != 0:
            next_pow2 = 1 << (n - 1).bit_length()
            signal = signal + [0j] * (next_pow2 - n)
            n = next_pow2

        if n <= 1:
            return signal

        even = SignalProcessing.fft(signal[0::2])
        odd = SignalProcessing.fft(signal[1::2])

        result = [0j] * n
        for k in range(n // 2):
            angle = -2 * math.pi * k / n
            twiddle = complex(math.cos(angle), math.sin(angle)) * odd[k]
            result[k] = even[k] + twiddle
            result[k + n // 2] = even[k] - twiddle

        return result

    @staticmethod
    def convolve(signal1: List[float], signal2: List[float]) -> List[float]:
        """Linear convolution of two signals."""
        n1, n2 = len(signal1), len(signal2)
        result = [0.0] * (n1 + n2 - 1)
        for i in range(n1):
            for j in range(n2):
                result[i + j] += signal1[i] * signal2[j]
        return result

    @staticmethod
    def correlate(signal1: List[float], signal2: List[float]) -> List[float]:
        """Cross-correlation of two signals."""
        return SignalProcessing.convolve(signal1, signal2[::-1])

    @staticmethod
    def moving_average(signal: List[float], window_size: int) -> List[float]:
        """Calculate moving average."""
        if window_size < 1 or window_size > len(signal):
            raise ValueError("Invalid window size")

        result = []
        window_sum = sum(signal[:window_size])
        result.append(window_sum / window_size)

        for i in range(window_size, len(signal)):
            window_sum += signal[i] - signal[i - window_size]
            result.append(window_sum / window_size)

        return result

    @staticmethod
    def exponential_smoothing(signal: List[float], alpha: float) -> List[float]:
        """Exponential smoothing filter."""
        if not 0 < alpha <= 1:
            raise ValueError("Alpha must be in (0, 1]")

        result = [signal[0]]
        for i in range(1, len(signal)):
            result.append(alpha * signal[i] + (1 - alpha) * result[-1])
        return result

    @staticmethod
    def low_pass_filter(signal: List[float], cutoff: float,
                       sample_rate: float) -> List[float]:
        """Simple low-pass filter using moving average approximation."""
        window_size = max(1, int(sample_rate / (2 * cutoff)))
        return SignalProcessing.moving_average(signal, window_size)

    @staticmethod
    def high_pass_filter(signal: List[float], cutoff: float,
                        sample_rate: float) -> List[float]:
        """High-pass filter (signal - low-pass)."""
        low_passed = SignalProcessing.low_pass_filter(signal, cutoff, sample_rate)
        offset = (len(signal) - len(low_passed)) // 2
        result = []
        for i, val in enumerate(low_passed):
            result.append(signal[i + offset] - val)
        return result

    @staticmethod
    def autocorrelation(signal: List[float]) -> List[float]:
        """Calculate autocorrelation of signal."""
        n = len(signal)
        mean = sum(signal) / n
        centered = [x - mean for x in signal]

        result = []
        for lag in range(n):
            corr = sum(centered[i] * centered[i + lag] for i in range(n - lag))
            result.append(corr / (n - lag))

        return result

    @staticmethod
    def power_spectrum(signal: List[float]) -> List[float]:
        """Calculate power spectrum of signal."""
        fft_result = SignalProcessing.fft([complex(x) for x in signal])
        return [abs(x) ** 2 for x in fft_result[:len(fft_result)//2 + 1]]


# =============================================================================
# SECTION 7: OPTIMIZATION ALGORITHMS
# =============================================================================

class Optimization:
    """Optimization algorithms for finding minima/maxima."""

    @staticmethod
    def gradient_descent(f: Callable[..., float], initial: List[float],
                        learning_rate: float = 0.01, max_iter: int = 10000,
                        tol: float = 1e-8) -> Tuple[List[float], float]:
        """Gradient descent optimization."""
        x = initial.copy()

        for _ in range(max_iter):
            grad = NumericalAnalysis.gradient(f, x)
            new_x = [xi - learning_rate * gi for xi, gi in zip(x, grad)]

            if math.sqrt(sum((a - b)**2 for a, b in zip(new_x, x))) < tol:
                return new_x, f(*new_x)

            x = new_x

        return x, f(*x)

    @staticmethod
    def adam_optimizer(f: Callable[..., float], initial: List[float],
                      learning_rate: float = 0.001, beta1: float = 0.9,
                      beta2: float = 0.999, epsilon: float = 1e-8,
                      max_iter: int = 10000, tol: float = 1e-8) -> Tuple[List[float], float]:
        """Adam optimization algorithm."""
        x = initial.copy()
        m = [0.0] * len(x)
        v = [0.0] * len(x)

        for t in range(1, max_iter + 1):
            grad = NumericalAnalysis.gradient(f, x)

            m = [beta1 * mi + (1 - beta1) * gi for mi, gi in zip(m, grad)]
            v = [beta2 * vi + (1 - beta2) * gi**2 for vi, gi in zip(v, grad)]

            m_hat = [mi / (1 - beta1**t) for mi in m]
            v_hat = [vi / (1 - beta2**t) for vi in v]

            new_x = [xi - learning_rate * mhi / (math.sqrt(vhi) + epsilon)
                    for xi, mhi, vhi in zip(x, m_hat, v_hat)]

            if math.sqrt(sum((a - b)**2 for a, b in zip(new_x, x))) < tol:
                return new_x, f(*new_x)

            x = new_x

        return x, f(*x)

    @staticmethod
    def simulated_annealing(f: Callable[..., float], initial: List[float],
                           temp_initial: float = 100, temp_final: float = 1e-8,
                           cooling_rate: float = 0.995, max_iter: int = 10000,
                           step_size: float = 1.0) -> Tuple[List[float], float]:
        """Simulated annealing optimization."""
        current = initial.copy()
        current_energy = f(*current)
        best = current.copy()
        best_energy = current_energy
        temp = temp_initial

        for _ in range(max_iter):
            if temp < temp_final:
                break

            neighbor = [x + random.gauss(0, step_size) for x in current]
            neighbor_energy = f(*neighbor)

            delta = neighbor_energy - current_energy

            if delta < 0 or random.random() < math.exp(-delta / temp):
                current = neighbor
                current_energy = neighbor_energy

                if current_energy < best_energy:
                    best = current.copy()
                    best_energy = current_energy

            temp *= cooling_rate

        return best, best_energy

    @staticmethod
    def particle_swarm(f: Callable[..., float], bounds: List[Tuple[float, float]],
                      n_particles: int = 30, max_iter: int = 100,
                      w: float = 0.7, c1: float = 1.5, c2: float = 1.5) -> Tuple[List[float], float]:
        """Particle Swarm Optimization."""
        dim = len(bounds)

        positions = [[random.uniform(bounds[d][0], bounds[d][1])
                     for d in range(dim)] for _ in range(n_particles)]
        velocities = [[random.uniform(-1, 1) for _ in range(dim)]
                     for _ in range(n_particles)]

        personal_best = [p.copy() for p in positions]
        personal_best_scores = [f(*p) for p in positions]

        global_best_idx = min(range(n_particles), key=lambda i: personal_best_scores[i])
        global_best = personal_best[global_best_idx].copy()
        global_best_score = personal_best_scores[global_best_idx]

        for _ in range(max_iter):
            for i in range(n_particles):
                r1, r2 = random.random(), random.random()

                for d in range(dim):
                    velocities[i][d] = (w * velocities[i][d] +
                                       c1 * r1 * (personal_best[i][d] - positions[i][d]) +
                                       c2 * r2 * (global_best[d] - positions[i][d]))
                    positions[i][d] += velocities[i][d]
                    positions[i][d] = max(bounds[d][0], min(bounds[d][1], positions[i][d]))

                score = f(*positions[i])
                if score < personal_best_scores[i]:
                    personal_best[i] = positions[i].copy()
                    personal_best_scores[i] = score

                    if score < global_best_score:
                        global_best = positions[i].copy()
                        global_best_score = score

        return global_best, global_best_score

    @staticmethod
    def genetic_algorithm(fitness: Callable[[List[float]], float],
                         bounds: List[Tuple[float, float]],
                         pop_size: int = 50, generations: int = 100,
                         mutation_rate: float = 0.1,
                         crossover_rate: float = 0.8) -> Tuple[List[float], float]:
        """Genetic algorithm optimization (minimization)."""
        dim = len(bounds)

        population = [[random.uniform(bounds[d][0], bounds[d][1])
                      for d in range(dim)] for _ in range(pop_size)]

        def evaluate(individual):
            return fitness(individual)

        for _ in range(generations):
            scores = [evaluate(ind) for ind in population]

            sorted_indices = sorted(range(pop_size), key=lambda i: scores[i])
            population = [population[i] for i in sorted_indices]
            scores = [scores[i] for i in sorted_indices]

            new_population = population[:pop_size // 5]

            while len(new_population) < pop_size:
                if random.random() < crossover_rate:
                    p1 = population[random.randint(0, pop_size // 3)]
                    p2 = population[random.randint(0, pop_size // 3)]
                    crossover_point = random.randint(1, dim - 1)
                    child = p1[:crossover_point] + p2[crossover_point:]
                else:
                    child = random.choice(population[:pop_size // 3]).copy()

                for d in range(dim):
                    if random.random() < mutation_rate:
                        child[d] = random.uniform(bounds[d][0], bounds[d][1])

                new_population.append(child)

            population = new_population

        best_idx = min(range(pop_size), key=lambda i: evaluate(population[i]))
        return population[best_idx], evaluate(population[best_idx])

    @staticmethod
    def nelder_mead(f: Callable[..., float], initial: List[float],
                   alpha: float = 1.0, gamma: float = 2.0,
                   rho: float = 0.5, sigma: float = 0.5,
                   max_iter: int = 1000, tol: float = 1e-8) -> Tuple[List[float], float]:
        """Nelder-Mead simplex optimization."""
        n = len(initial)

        simplex = [initial.copy()]
        for i in range(n):
            point = initial.copy()
            point[i] += 1.0
            simplex.append(point)

        for _ in range(max_iter):
            simplex.sort(key=lambda x: f(*x))

            centroid = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]

            if math.sqrt(sum((f(*simplex[i]) - f(*simplex[0]))**2 for i in range(n+1))) < tol:
                break

            reflected = [centroid[j] + alpha * (centroid[j] - simplex[-1][j])
                        for j in range(n)]
            fr = f(*reflected)

            if f(*simplex[0]) <= fr < f(*simplex[-2]):
                simplex[-1] = reflected
                continue

            if fr < f(*simplex[0]):
                expanded = [centroid[j] + gamma * (reflected[j] - centroid[j])
                           for j in range(n)]
                if f(*expanded) < fr:
                    simplex[-1] = expanded
                else:
                    simplex[-1] = reflected
                continue

            contracted = [centroid[j] + rho * (simplex[-1][j] - centroid[j])
                         for j in range(n)]
            if f(*contracted) < f(*simplex[-1]):
                simplex[-1] = contracted
                continue

            for i in range(1, n + 1):
                simplex[i] = [simplex[0][j] + sigma * (simplex[i][j] - simplex[0][j])
                             for j in range(n)]

        simplex.sort(key=lambda x: f(*x))
        return simplex[0], f(*simplex[0])


# =============================================================================
# SECTION 8: INTERPOLATION AND APPROXIMATION
# =============================================================================

class Interpolation:
    """Interpolation and curve fitting methods."""

    @staticmethod
    def lagrange(x_points: List[float], y_points: List[float], x: float) -> float:
        """Lagrange polynomial interpolation."""
        if len(x_points) != len(y_points):
            raise ValueError("x and y must have same length")

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
    def newton_divided_diff(x_points: List[float], y_points: List[float],
                           x: float) -> float:
        """Newton's divided difference interpolation."""
        n = len(x_points)
        coef = [[0.0] * n for _ in range(n)]

        for i in range(n):
            coef[i][0] = y_points[i]

        for j in range(1, n):
            for i in range(n - j):
                coef[i][j] = ((coef[i+1][j-1] - coef[i][j-1]) /
                             (x_points[i+j] - x_points[i]))

        result = coef[0][0]
        product = 1.0
        for i in range(1, n):
            product *= (x - x_points[i-1])
            result += coef[0][i] * product

        return result

    @staticmethod
    def cubic_spline(x_points: List[float], y_points: List[float],
                    x_new: List[float]) -> List[float]:
        """Natural cubic spline interpolation."""
        n = len(x_points)
        if n < 2:
            raise ValueError("Need at least 2 points")

        h = [x_points[i+1] - x_points[i] for i in range(n-1)]

        alpha = [0.0] * n
        for i in range(1, n-1):
            alpha[i] = (3/h[i] * (y_points[i+1] - y_points[i]) -
                       3/h[i-1] * (y_points[i] - y_points[i-1]))

        l = [1.0] + [0.0] * (n-1)
        mu = [0.0] * n
        z = [0.0] * n

        for i in range(1, n-1):
            l[i] = 2 * (x_points[i+1] - x_points[i-1]) - h[i-1] * mu[i-1]
            mu[i] = h[i] / l[i]
            z[i] = (alpha[i] - h[i-1] * z[i-1]) / l[i]

        l[n-1] = 1.0
        z[n-1] = 0.0

        c = [0.0] * n
        b = [0.0] * (n-1)
        d = [0.0] * (n-1)

        for j in range(n-2, -1, -1):
            c[j] = z[j] - mu[j] * c[j+1]
            b[j] = ((y_points[j+1] - y_points[j]) / h[j] -
                   h[j] * (c[j+1] + 2*c[j]) / 3)
            d[j] = (c[j+1] - c[j]) / (3 * h[j])

        result = []
        for x in x_new:
            idx = 0
            for i in range(n-1):
                if x_points[i] <= x <= x_points[i+1]:
                    idx = i
                    break

            dx = x - x_points[idx]
            y = (y_points[idx] + b[idx]*dx + c[idx]*dx**2 + d[idx]*dx**3)
            result.append(y)

        return result

    @staticmethod
    def polynomial_fit(x_points: List[float], y_points: List[float],
                      degree: int) -> List[float]:
        """Polynomial least squares fitting. Returns coefficients."""
        n = len(x_points)
        if n <= degree:
            raise ValueError("Need more points than polynomial degree")

        X = [[x_points[i]**j for j in range(degree + 1)] for i in range(n)]

        XtX = [[sum(X[k][i] * X[k][j] for k in range(n))
               for j in range(degree + 1)] for i in range(degree + 1)]
        XtY = [sum(X[k][i] * y_points[k] for k in range(n))
              for i in range(degree + 1)]

        matrix = Matrix(XtX)
        coefficients = matrix.solve_linear_system(XtY)

        return coefficients

    @staticmethod
    def evaluate_polynomial(coefficients: List[float], x: float) -> float:
        """Evaluate polynomial using Horner's method."""
        result = 0.0
        for coef in reversed(coefficients):
            result = result * x + coef
        return result


# =============================================================================
# SECTION 9: DIFFERENTIAL EQUATIONS
# =============================================================================

class DifferentialEquations:
    """Numerical methods for solving differential equations."""

    @staticmethod
    def euler_method(f: Callable[[float, float], float], y0: float,
                    t_span: Tuple[float, float], n_steps: int) -> Tuple[List[float], List[float]]:
        """Solve ODE using Euler's method. dy/dt = f(t, y)"""
        t0, tf = t_span
        h = (tf - t0) / n_steps

        t_values = [t0]
        y_values = [y0]

        t, y = t0, y0
        for _ in range(n_steps):
            y = y + h * f(t, y)
            t = t + h
            t_values.append(t)
            y_values.append(y)

        return t_values, y_values

    @staticmethod
    def runge_kutta_4(f: Callable[[float, float], float], y0: float,
                     t_span: Tuple[float, float], n_steps: int) -> Tuple[List[float], List[float]]:
        """Solve ODE using 4th order Runge-Kutta method."""
        t0, tf = t_span
        h = (tf - t0) / n_steps

        t_values = [t0]
        y_values = [y0]

        t, y = t0, y0
        for _ in range(n_steps):
            k1 = h * f(t, y)
            k2 = h * f(t + h/2, y + k1/2)
            k3 = h * f(t + h/2, y + k2/2)
            k4 = h * f(t + h, y + k3)

            y = y + (k1 + 2*k2 + 2*k3 + k4) / 6
            t = t + h

            t_values.append(t)
            y_values.append(y)

        return t_values, y_values

    @staticmethod
    def runge_kutta_system(f: Callable[[float, List[float]], List[float]],
                          y0: List[float], t_span: Tuple[float, float],
                          n_steps: int) -> Tuple[List[float], List[List[float]]]:
        """Solve system of ODEs using RK4."""
        t0, tf = t_span
        h = (tf - t0) / n_steps
        n = len(y0)

        t_values = [t0]
        y_values = [y0.copy()]

        t = t0
        y = y0.copy()

        for _ in range(n_steps):
            k1 = [h * fi for fi in f(t, y)]
            k2 = [h * fi for fi in f(t + h/2, [y[i] + k1[i]/2 for i in range(n)])]
            k3 = [h * fi for fi in f(t + h/2, [y[i] + k2[i]/2 for i in range(n)])]
            k4 = [h * fi for fi in f(t + h, [y[i] + k3[i] for i in range(n)])]

            y = [y[i] + (k1[i] + 2*k2[i] + 2*k3[i] + k4[i])/6 for i in range(n)]
            t = t + h

            t_values.append(t)
            y_values.append(y.copy())

        return t_values, y_values

    @staticmethod
    def adams_bashforth_4(f: Callable[[float, float], float], y0: float,
                         t_span: Tuple[float, float], n_steps: int) -> Tuple[List[float], List[float]]:
        """Solve ODE using 4th order Adams-Bashforth method."""
        t0, tf = t_span
        h = (tf - t0) / n_steps

        t_init, y_init = DifferentialEquations.runge_kutta_4(f, y0, (t0, t0 + 3*h), 3)

        t_values = t_init.copy()
        y_values = y_init.copy()

        for i in range(3, n_steps):
            t = t_values[-1] + h

            f_n = f(t_values[-1], y_values[-1])
            f_n1 = f(t_values[-2], y_values[-2])
            f_n2 = f(t_values[-3], y_values[-3])
            f_n3 = f(t_values[-4], y_values[-4])

            y = y_values[-1] + h * (55*f_n - 59*f_n1 + 37*f_n2 - 9*f_n3) / 24

            t_values.append(t)
            y_values.append(y)

        return t_values, y_values

    @staticmethod
    def finite_difference_bvp(p: Callable[[float], float],
                             q: Callable[[float], float],
                             r: Callable[[float], float],
                             a: float, b: float, alpha: float, beta: float,
                             n: int) -> Tuple[List[float], List[float]]:
        """Solve boundary value problem y'' + p(x)y' + q(x)y = r(x)."""
        h = (b - a) / (n + 1)
        x_values = [a + i * h for i in range(n + 2)]

        A = Matrix.zeros(n, n)
        B = [0.0] * n

        for i in range(n):
            xi = x_values[i + 1]
            pi, qi, ri = p(xi), q(xi), r(xi)

            if i > 0:
                A[i, i-1] = 1 - h * pi / 2
            A[i, i] = -2 + h * h * qi
            if i < n - 1:
                A[i, i+1] = 1 + h * pi / 2

            B[i] = h * h * ri
            if i == 0:
                B[i] -= (1 - h * pi / 2) * alpha
            if i == n - 1:
                B[i] -= (1 + h * pi / 2) * beta

        y_interior = A.solve_linear_system(B)
        y_values = [alpha] + y_interior + [beta]

        return x_values, y_values


# =============================================================================
# SECTION 10: COMPLEX NUMBER OPERATIONS
# =============================================================================

class ComplexAnalysis:
    """Operations on complex numbers and complex analysis."""

    @staticmethod
    def polar_to_rect(r: float, theta: float) -> complex:
        """Convert polar to rectangular form."""
        return complex(r * math.cos(theta), r * math.sin(theta))

    @staticmethod
    def rect_to_polar(z: complex) -> Tuple[float, float]:
        """Convert rectangular to polar form."""
        return abs(z), math.atan2(z.imag, z.real)

    @staticmethod
    def complex_exp(z: complex) -> complex:
        """Complex exponential."""
        return math.exp(z.real) * complex(math.cos(z.imag), math.sin(z.imag))

    @staticmethod
    def complex_log(z: complex) -> complex:
        """Complex natural logarithm (principal branch)."""
        r, theta = ComplexAnalysis.rect_to_polar(z)
        return complex(math.log(r), theta)

    @staticmethod
    def complex_pow(base: complex, exp: complex) -> complex:
        """Complex power: base^exp."""
        if base == 0:
            return 0 if exp.real > 0 else complex(float('inf'), 0)
        return ComplexAnalysis.complex_exp(exp * ComplexAnalysis.complex_log(base))

    @staticmethod
    def complex_sin(z: complex) -> complex:
        """Complex sine."""
        return complex(math.sin(z.real) * math.cosh(z.imag),
                      math.cos(z.real) * math.sinh(z.imag))

    @staticmethod
    def complex_cos(z: complex) -> complex:
        """Complex cosine."""
        return complex(math.cos(z.real) * math.cosh(z.imag),
                      -math.sin(z.real) * math.sinh(z.imag))

    @staticmethod
    def nth_roots(z: complex, n: int) -> List[complex]:
        """Find all n-th roots of complex number."""
        r, theta = ComplexAnalysis.rect_to_polar(z)
        r_root = r ** (1/n)

        roots = []
        for k in range(n):
            angle = (theta + 2 * math.pi * k) / n
            roots.append(ComplexAnalysis.polar_to_rect(r_root, angle))

        return roots

    @staticmethod
    def contour_integral(f: Callable[[complex], complex],
                        path: List[complex]) -> complex:
        """Numerical contour integration along path."""
        result = 0j
        for i in range(len(path) - 1):
            z1, z2 = path[i], path[i + 1]
            dz = z2 - z1
            z_mid = (z1 + z2) / 2
            result += f(z_mid) * dz
        return result

    @staticmethod
    def residue(f: Callable[[complex], complex], z0: complex,
               radius: float = 0.01, n_points: int = 100) -> complex:
        """Estimate residue at z0 using contour integration."""
        path = [z0 + radius * ComplexAnalysis.polar_to_rect(1, 2*math.pi*k/n_points)
               for k in range(n_points + 1)]
        integral = ComplexAnalysis.contour_integral(f, path)
        return integral / (2j * math.pi)


# =============================================================================
# SECTION 11: GRAPH AND COMBINATORICS
# =============================================================================

class GraphAlgorithms:
    """Graph theory algorithms."""

    @staticmethod
    def dijkstra(graph: Dict[int, List[Tuple[int, float]]],
                start: int) -> Dict[int, float]:
        """Dijkstra's shortest path algorithm."""
        distances = {start: 0}
        visited = set()

        while len(visited) < len(graph):
            current = None
            min_dist = float('inf')
            for node, dist in distances.items():
                if node not in visited and dist < min_dist:
                    current = node
                    min_dist = dist

            if current is None:
                break

            visited.add(current)

            if current in graph:
                for neighbor, weight in graph[current]:
                    new_dist = distances[current] + weight
                    if neighbor not in distances or new_dist < distances[neighbor]:
                        distances[neighbor] = new_dist

        return distances

    @staticmethod
    def floyd_warshall(n: int, edges: List[Tuple[int, int, float]]) -> List[List[float]]:
        """Floyd-Warshall all-pairs shortest path."""
        INF = float('inf')
        dist = [[INF if i != j else 0 for j in range(n)] for i in range(n)]

        for u, v, w in edges:
            dist[u][v] = w

        for k in range(n):
            for i in range(n):
                for j in range(n):
                    if dist[i][k] + dist[k][j] < dist[i][j]:
                        dist[i][j] = dist[i][k] + dist[k][j]

        return dist

    @staticmethod
    def bellman_ford(n: int, edges: List[Tuple[int, int, float]],
                    start: int) -> Tuple[List[float], bool]:
        """Bellman-Ford algorithm. Returns distances and whether negative cycle exists."""
        INF = float('inf')
        dist = [INF] * n
        dist[start] = 0

        for _ in range(n - 1):
            for u, v, w in edges:
                if dist[u] != INF and dist[u] + w < dist[v]:
                    dist[v] = dist[u] + w

        has_negative_cycle = False
        for u, v, w in edges:
            if dist[u] != INF and dist[u] + w < dist[v]:
                has_negative_cycle = True
                break

        return dist, has_negative_cycle

    @staticmethod
    def topological_sort(graph: Dict[int, List[int]]) -> List[int]:
        """Topological sort using DFS."""
        visited = set()
        result = []

        def dfs(node):
            if node in visited:
                return
            visited.add(node)
            if node in graph:
                for neighbor in graph[node]:
                    dfs(neighbor)
            result.append(node)

        for node in graph:
            dfs(node)

        return result[::-1]

    @staticmethod
    def kruskal_mst(n: int, edges: List[Tuple[int, int, float]]) -> List[Tuple[int, int, float]]:
        """Kruskal's minimum spanning tree algorithm."""
        parent = list(range(n))
        rank = [0] * n

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px == py:
                return False
            if rank[px] < rank[py]:
                px, py = py, px
            parent[py] = px
            if rank[px] == rank[py]:
                rank[px] += 1
            return True

        edges = sorted(edges, key=lambda e: e[2])
        mst = []

        for u, v, w in edges:
            if union(u, v):
                mst.append((u, v, w))
                if len(mst) == n - 1:
                    break

        return mst

    @staticmethod
    def strongly_connected_components(graph: Dict[int, List[int]]) -> List[List[int]]:
        """Find SCCs using Kosaraju's algorithm."""
        visited = set()
        order = []

        def dfs1(node):
            if node in visited:
                return
            visited.add(node)
            if node in graph:
                for neighbor in graph[node]:
                    dfs1(neighbor)
            order.append(node)

        all_nodes = set(graph.keys())
        for node in graph.values():
            all_nodes.update(node)

        for node in all_nodes:
            dfs1(node)

        reverse_graph = defaultdict(list)
        for u in graph:
            for v in graph[u]:
                reverse_graph[v].append(u)

        visited.clear()
        sccs = []

        def dfs2(node, component):
            if node in visited:
                return
            visited.add(node)
            component.append(node)
            for neighbor in reverse_graph[node]:
                dfs2(neighbor, component)

        for node in reversed(order):
            if node not in visited:
                component = []
                dfs2(node, component)
                sccs.append(component)

        return sccs


# =============================================================================
# SECTION 12: NUMERICAL UTILITIES AND SPECIAL FUNCTIONS
# =============================================================================

class SpecialFunctions:
    """Special mathematical functions."""

    @staticmethod
    def erf(x: float) -> float:
        """Error function using series approximation."""
        return math.erf(x)

    @staticmethod
    def erfc(x: float) -> float:
        """Complementary error function."""
        return 1 - SpecialFunctions.erf(x)

    @staticmethod
    def bessel_j0(x: float) -> float:
        """Bessel function of the first kind, order 0."""
        if abs(x) < 8:
            y = x * x
            return (57568490574.0 + y*(-13362590354.0 + y*(651619640.7 +
                   y*(-11214424.18 + y*(77392.33017 + y*(-184.9052456)))))) / \
                   (57568490411.0 + y*(1029532985.0 + y*(9494680.718 +
                   y*(59272.64853 + y*(267.8532712 + y)))))

        ax = abs(x)
        z = 8.0 / ax
        y = z * z
        xx = ax - 0.785398164

        p0 = 1.0 + y*(-0.1098628627e-2 + y*(0.2734510407e-4 +
            y*(-0.2073370639e-5 + y*0.2093887211e-6)))
        q0 = -0.1562499995e-1 + y*(0.1430488765e-3 + y*(-0.6911147651e-5 +
            y*(0.7621095161e-6 - y*0.934945152e-7)))

        return math.sqrt(0.636619772 / ax) * (math.cos(xx)*p0 - z*math.sin(xx)*q0)

    @staticmethod
    def bessel_j1(x: float) -> float:
        """Bessel function of the first kind, order 1."""
        if abs(x) < 8:
            y = x * x
            result = x * (72362614232.0 + y*(-7895059235.0 + y*(242396853.1 +
                    y*(-2972611.439 + y*(15704.48260 + y*(-30.16036606)))))) / \
                    (144725228442.0 + y*(2300535178.0 + y*(18583304.74 +
                    y*(99447.43394 + y*(376.9991397 + y)))))
            return result

        ax = abs(x)
        z = 8.0 / ax
        y = z * z
        xx = ax - 2.356194491

        p1 = 1.0 + y*(0.183105e-2 + y*(-0.3516396496e-4 +
            y*(0.2457520174e-5 - y*0.240337019e-6)))
        q1 = 0.04687499995 + y*(-0.2002690873e-3 + y*(0.8449199096e-5 +
            y*(-0.88228987e-6 + y*0.105787412e-6)))

        result = math.sqrt(0.636619772 / ax) * (math.cos(xx)*p1 - z*math.sin(xx)*q1)
        return result if x >= 0 else -result

    @staticmethod
    def legendre_p(n: int, x: float) -> float:
        """Legendre polynomial P_n(x) using recurrence."""
        if n == 0:
            return 1.0
        if n == 1:
            return x

        p_prev, p_curr = 1.0, x
        for k in range(2, n + 1):
            p_next = ((2*k - 1) * x * p_curr - (k - 1) * p_prev) / k
            p_prev, p_curr = p_curr, p_next

        return p_curr

    @staticmethod
    def chebyshev_t(n: int, x: float) -> float:
        """Chebyshev polynomial of the first kind T_n(x)."""
        if n == 0:
            return 1.0
        if n == 1:
            return x

        t_prev, t_curr = 1.0, x
        for _ in range(2, n + 1):
            t_next = 2 * x * t_curr - t_prev
            t_prev, t_curr = t_curr, t_next

        return t_curr

    @staticmethod
    def hermite_h(n: int, x: float) -> float:
        """Hermite polynomial H_n(x) (physicist's convention)."""
        if n == 0:
            return 1.0
        if n == 1:
            return 2 * x

        h_prev, h_curr = 1.0, 2 * x
        for k in range(2, n + 1):
            h_next = 2 * x * h_curr - 2 * (k - 1) * h_prev
            h_prev, h_curr = h_curr, h_next

        return h_curr

    @staticmethod
    def laguerre_l(n: int, x: float) -> float:
        """Laguerre polynomial L_n(x)."""
        if n == 0:
            return 1.0
        if n == 1:
            return 1 - x

        l_prev, l_curr = 1.0, 1 - x
        for k in range(2, n + 1):
            l_next = ((2*k - 1 - x) * l_curr - (k - 1) * l_prev) / k
            l_prev, l_curr = l_curr, l_next

        return l_curr


# =============================================================================
# DEMONSTRATION AND TESTING
# =============================================================================

def demonstrate_calculations():
    """Demonstrate various calculations from the library."""
    print("=" * 70)
    print("COMPLEX CALCULATIONS LIBRARY DEMONSTRATION")
    print("=" * 70)

    # Math utilities
    print("\n--- MATH UTILITIES ---")
    print(f"Factorial(10) = {MathUtils.factorial(10)}")
    print(f"Fibonacci(20) = {MathUtils.fibonacci(20)}")
    print(f"GCD(48, 18) = {MathUtils.gcd(48, 18)}")
    print(f"LCM(12, 18) = {MathUtils.lcm(12, 18)}")
    print(f"Is 997 prime? {MathUtils.is_prime(997)}")
    print(f"Prime factors of 84: {MathUtils.prime_factors(84)}")
    print(f"Primes up to 50: {MathUtils.sieve_of_eratosthenes(50)}")

    # Numerical analysis
    print("\n--- NUMERICAL ANALYSIS ---")
    f = lambda x: x**3 - 2*x - 5
    print(f"Root of x^3-2x-5 (Newton): {NumericalAnalysis.newton_raphson(f, 2):.10f}")
    print(f"Root of x^3-2x-5 (Bisection): {NumericalAnalysis.bisection(f, 2, 3):.10f}")

    g = lambda x: math.sin(x)
    print(f"Integral sin(x)dx from 0 to pi (Simpson): {NumericalAnalysis.integrate_simpson(g, 0, math.pi):.10f}")
    print(f"Integral sin(x)dx from 0 to pi (Romberg): {NumericalAnalysis.integrate_romberg(g, 0, math.pi):.10f}")
    print(f"d/dx(sin(x)) at x=0: {NumericalAnalysis.derivative(math.sin, 0):.10f}")

    # Matrix operations
    print("\n--- LINEAR ALGEBRA ---")
    A = Matrix([[4, 2, 1], [2, 5, 3], [1, 3, 6]])
    print("Matrix A:")
    print(A)
    print(f"\nDeterminant: {A.determinant():.4f}")
    print(f"Trace: {A.trace():.4f}")

    eigenval, eigenvec = A.eigenvalues_power_iteration()
    print(f"Dominant eigenvalue: {eigenval:.4f}")

    b = [1, 2, 3]
    x = A.solve_linear_system(b)
    print(f"Solution to Ax = [1,2,3]: {[f'{xi:.4f}' for xi in x]}")

    # Statistics
    print("\n--- STATISTICS ---")
    data = [2.5, 3.1, 2.8, 4.2, 3.6, 2.9, 3.8, 3.2, 4.0, 3.5]
    print(f"Data: {data}")
    print(f"Mean: {Statistics.mean(data):.4f}")
    print(f"Median: {Statistics.median(data):.4f}")
    print(f"Std Dev: {Statistics.std_dev(data):.4f}")
    print(f"Variance: {Statistics.variance(data):.4f}")
    print(f"Skewness: {Statistics.skewness(data):.4f}")

    x_data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    y_data = [2.1, 4.2, 5.8, 8.1, 10.2, 11.9, 14.1, 16.0, 18.2, 20.1]
    slope, intercept, r_sq = Statistics.linear_regression(x_data, y_data)
    print(f"\nLinear regression: y = {slope:.4f}x + {intercept:.4f}, R^2 = {r_sq:.4f}")

    # Probability distributions
    print("\n--- PROBABILITY DISTRIBUTIONS ---")
    print(f"Normal PDF(0, mu=0, sigma=1): {Distributions.normal_pdf(0):.6f}")
    print(f"Normal CDF(1.96, mu=0, sigma=1): {Distributions.normal_cdf(1.96):.6f}")
    print(f"Binomial PMF(3, n=10, p=0.5): {Distributions.binomial_pmf(3, 10, 0.5):.6f}")
    print(f"Poisson PMF(2, lambda=3): {Distributions.poisson_pmf(2, 3):.6f}")
    print(f"Gamma(5): {Distributions.gamma_function(5):.6f}")

    # Signal processing
    print("\n--- SIGNAL PROCESSING ---")
    signal = [math.sin(2 * math.pi * i / 16) for i in range(16)]
    fft_result = SignalProcessing.fft([complex(x) for x in signal])
    print(f"FFT of sine wave (first 5 magnitudes): {[f'{abs(x):.4f}' for x in fft_result[:5]]}")

    noisy_signal = [x + random.gauss(0, 0.1) for x in signal]
    smoothed = SignalProcessing.moving_average(noisy_signal, 3)
    print(f"Moving average (window=3) applied to noisy signal")

    # Optimization
    print("\n--- OPTIMIZATION ---")
    rosenbrock = lambda x, y: (1 - x)**2 + 100 * (y - x**2)**2

    result, value = Optimization.gradient_descent(rosenbrock, [0.0, 0.0],
                                                  learning_rate=0.001, max_iter=50000)
    print(f"Gradient descent on Rosenbrock: x={result[0]:.4f}, y={result[1]:.4f}, f(x,y)={value:.6f}")

    result, value = Optimization.nelder_mead(rosenbrock, [0.0, 0.0])
    print(f"Nelder-Mead on Rosenbrock: x={result[0]:.4f}, y={result[1]:.4f}, f(x,y)={value:.6f}")

    # Interpolation
    print("\n--- INTERPOLATION ---")
    x_pts = [0, 1, 2, 3, 4]
    y_pts = [1, 2.7, 7.4, 20.1, 54.6]  # approximately e^x
    print(f"Lagrange interpolation at x=2.5: {Interpolation.lagrange(x_pts, y_pts, 2.5):.4f}")
    print(f"Expected (e^2.5): {math.exp(2.5):.4f}")

    # Differential equations
    print("\n--- DIFFERENTIAL EQUATIONS ---")
    ode = lambda t, y: -2 * y  # dy/dt = -2y, solution: y = e^(-2t)
    t_vals, y_vals = DifferentialEquations.runge_kutta_4(ode, 1.0, (0, 2), 100)
    print(f"RK4 solution of dy/dt = -2y at t=2: {y_vals[-1]:.6f}")
    print(f"Exact solution at t=2: {math.exp(-4):.6f}")

    # Complex analysis
    print("\n--- COMPLEX ANALYSIS ---")
    z = complex(1, 1)
    print(f"z = 1+i")
    print(f"Polar form: r={abs(z):.4f}, theta={math.atan2(z.imag, z.real):.4f}")
    print(f"exp(z): {ComplexAnalysis.complex_exp(z)}")
    print(f"Cube roots of 1+i: {[f'({r.real:.4f}+{r.imag:.4f}i)' for r in ComplexAnalysis.nth_roots(z, 3)]}")

    # Graph algorithms
    print("\n--- GRAPH ALGORITHMS ---")
    graph = {
        0: [(1, 4), (2, 1)],
        1: [(3, 1)],
        2: [(1, 2), (3, 5)],
        3: []
    }
    distances = GraphAlgorithms.dijkstra(graph, 0)
    print(f"Dijkstra shortest paths from node 0: {distances}")

    edges = [(0, 1, 4), (0, 2, 1), (1, 2, 2), (1, 3, 1), (2, 3, 5)]
    mst = GraphAlgorithms.kruskal_mst(4, edges)
    print(f"MST edges: {mst}")

    # Special functions
    print("\n--- SPECIAL FUNCTIONS ---")
    print(f"Bessel J0(1): {SpecialFunctions.bessel_j0(1):.6f}")
    print(f"Bessel J1(1): {SpecialFunctions.bessel_j1(1):.6f}")
    print(f"Legendre P3(0.5): {SpecialFunctions.legendre_p(3, 0.5):.6f}")
    print(f"Chebyshev T4(0.5): {SpecialFunctions.chebyshev_t(4, 0.5):.6f}")
    print(f"Hermite H3(1): {SpecialFunctions.hermite_h(3, 1):.6f}")
    print(f"Laguerre L3(1): {SpecialFunctions.laguerre_l(3, 1):.6f}")

    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    demonstrate_calculations()
