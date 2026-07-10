# Convolutions, Weights, and Normalization

Study notes converted from the KNN Lecture 3 slide deck.

## Overview

This lecture connects neural-network activations and initialization with
normalization and stochastic optimization. The main goal is stable learning:
keep activations and gradients at useful scales, then use an optimizer that
makes effective updates from mini-batches.

## Activations and initialization

### Interaction with non-linear activations

Weights and activation functions interact. If activations repeatedly enter
saturated regions, gradients become very small and earlier layers learn slowly.
Conversely, excessively large activations or weights can make optimization
unstable.

### Activation energy and output scale

The deck frames this as controlling activation energy. At initialization, the
network should avoid both of these failure modes:

- **Low energy:** signals and gradients decay through layers.
- **High energy:** signals or gradients grow too much.

The lecture points to Xavier Glorot and Yoshua Bengio's work on the difficulty
of training deep feed-forward networks, and to James Dellinger's overview of
weight initialization. The practical takeaway is that initialization should
consider both fan-in/fan-out and the chosen activation function.

## Normalization

### Batch normalization

Batch normalization normalizes intermediate activations using statistics from a
mini-batch, then learns a scale and shift. It was introduced by Ioffe and
Szegedy (2015) to make deep-network training faster and more stable.

At a high level, for an activation \(x\), batch normalization computes a
mini-batch mean and variance, normalizes \(x\), then applies learned parameters
\(\gamma\) and \(\beta\):

\[
\hat{x} = \frac{x - \mu_B}{\sqrt{\sigma_B^2 + \epsilon}}, \qquad
y = \gamma\hat{x} + \beta
\]

During inference, it uses accumulated running statistics instead of the current
batch's statistics.

### Other normalization methods

The deck also points to an overview of normalization methods. Important variants
include layer normalization, instance normalization, and group normalization;
the appropriate choice depends on architecture and batch size.

## Full training loop

Training follows this repeated process:

1. **Forward pass:** compute predictions from the current parameters.
2. **Loss computation:** compare predictions to targets.
3. **Backward pass:** use the chain rule/backpropagation to compute derivatives
   of the objective with respect to network parameters.
4. **Optimizer update:** change parameters using the gradients.

## Mini-batch stochastic gradient descent

Computing an exact gradient over a large whole dataset before every update is
expensive. Stochastic or mini-batch gradient descent instead estimates the
gradient from a small randomly selected mini-batch.

- Full-batch gradient descent gives the exact training-set gradient.
- Mini-batch SGD gives a noisy approximation, but performs far more frequent
  updates and is much more practical for large datasets.

## SGD with momentum and Nesterov momentum

Momentum maintains a velocity vector, accumulating directions that consistently
reduce the objective:

\[
v_t = \gamma v_{t-1} - \alpha\frac{\partial J(\theta_{t-1})}{\partial\theta},
\qquad
\theta_t = \theta_{t-1} + v_t
\]

Here \(\alpha\) is the learning rate and \(\gamma\) controls momentum. Momentum
smooths noisy gradients and accelerates progress along persistent directions.

Nesterov momentum evaluates the gradient after looking ahead by the previous
velocity:

\[
v_t = \gamma v_{t-1} - \alpha
\frac{\partial J(\theta_{t-1} + \gamma v_{t-1})}{\partial\theta},
\qquad
\theta_t = \theta_{t-1} + v_t
\]

## Adaptive optimizers

### Adagrad

Adagrad accumulates squared gradients per parameter and scales each update by
the inverse square root of that accumulator:

\[
acc_t = acc_{t-1} + \left(\frac{\partial J}{\partial\theta}\right)^2,
\qquad
\theta_t = \theta_{t-1} - \alpha
\frac{\partial J / \partial\theta}{\sqrt{acc_t} + \epsilon}
\]

Parameters with frequently large gradients receive smaller future steps. A
common downside is that the accumulated denominator can make learning rates
shrink too much over time.

### RMSProp

RMSProp replaces Adagrad's unbounded accumulator with an exponential moving
average:

\[
E_t = \gamma E_{t-1} + (1-\gamma)
\left(\frac{\partial J}{\partial\theta}\right)^2,
\qquad
\theta_t = \theta_{t-1} - \frac{\alpha}{\sqrt{E_t}}
\frac{\partial J}{\partial\theta}
\]

This retains per-parameter scaling without permanently decaying every effective
learning rate.

### Adam

Adam combines a first-moment estimate (momentum) with a second-moment estimate
(adaptive scaling):

\[
M_t = \beta_1 M_{t-1} + (1-\beta_1)\frac{\partial J}{\partial\theta}
\]

\[
E_t = \beta_2 E_{t-1} + (1-\beta_2)
\left(\frac{\partial J}{\partial\theta}\right)^2
\]

\[
\theta_t = \theta_{t-1} - \alpha
\frac{M_t}{\sqrt{E_t + \epsilon}}
\]

The lecture references Kingma and Ba's *Adam: A Method for Stochastic
Optimization* (2015). Adam is a common default because it generally works well
without extensive hand-tuning, though learning-rate schedules and optimizer
choice still matter.

## Key takeaways

1. Initialization and activation scale strongly affect whether gradients vanish
   or explode.
2. Normalization can stabilize intermediate distributions and speed training.
3. Mini-batch SGD makes large-scale learning computationally feasible.
4. Momentum improves SGD by smoothing and accelerating updates.
5. Adagrad, RMSProp, and Adam adapt updates per parameter using gradient-scale
   information.
