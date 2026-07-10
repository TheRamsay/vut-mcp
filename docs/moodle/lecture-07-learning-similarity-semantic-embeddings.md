# Learning Similarity and Semantic Embeddings

Study notes converted from the KNN Lecture 7 slide deck.

## Core idea

An embedding is a floating-point vector representation of an input. The goal is to make distance correspond to semantic similarity: matching examples are close and non-matching examples are farther away.

Embeddings work beyond a closed-set classifier because they can be compared to identities that were not present during training.

## Recognition tasks

| Task | Question | Typical supervision |
| --- | --- | --- |
| Verification | Are two inputs the same identity? | Same/different pairs |
| Identification | Which known identity is this? | Globally unique IDs |
| Re-identification | Has this identity appeared before? | Pairwise or weak labels |
| Retrieval | Which items match a query? | Relevance/ranking signals |

For identification, a network maps an image to an embedding, then a nearest-neighbour search against a database proposes the identity. A distance threshold can produce an **unknown** result.

## Distances

### Euclidean distance

\[
d(f_1, f_2) = \left[\sum_i (f_1[i]-f_2[i])^2\right]^{1/2} = \lVert f_1-f_2 \rVert
\]

### Cosine distance

\[
d(f_1, f_2) = 1 - \frac{f_1 \cdot f_2}{\lVert f_1 \rVert\lVert f_2 \rVert}
\]

For unit-normalized vectors, cosine and Euclidean distance induce the same similarity ordering.

## How to learn an embedding

### Classification features

Train an identity classifier with softmax and cross-entropy, remove the final classifier, and use the preceding activations as features. DeepFace is an early example; it used a weighted squared distance and an SVM for verification.

This baseline learns discriminative features but does not directly optimize pairwise embedding geometry.

### Siamese metric learning

Apply the same network \(f\) to two inputs and train from their embedding distance. The target says whether the pair is the same or different; the distance can be mapped to a probability and optimized with cross-entropy.

### Contrastive loss

For pair distance \(d_{1,2}\), same-pair indicator \(y\), and margin \(m\):

\[
l(d_{1,2}, y) = y\,d_{1,2} + (1-y)\max(0, m-d_{1,2})
\]

It pulls matching pairs together and pushes non-matching pairs apart until the margin is reached.

### Triplet loss

A triplet uses an anchor \(a\), a positive \(p\) of the same identity, and a negative \(n\) of a different identity:

\[
l(d_{a,p}, d_{a,n}) = \max(0, m + d_{a,p} - d_{a,n})
\]

The positive must be closer to the anchor than the negative by at least margin \(m\).

### Classification-margin methods

Classification can still create useful embedding spaces. A central (centre) loss pulls examples toward an identity prototype. ArcFace adds an angular margin to improve class separation for face recognition.

## Training details

### Hard mining

Focus training on hard positives and negatives rather than already-solved pairs. Mining may be offline from a previous model or online within the current minibatch.

### NT-Xent

NT-Xent is a temperature-scaled contrastive loss. It compares a positive pair against other examples in the batch and is widely used in self-supervised learning.

## Applications and modern methods

Embedding methods also support word embeddings, anomaly detection, zero-shot classification, and text/image retrieval.

- **CLIP** learns a shared text/image space from matching pairs.
- **SimCLR** uses two augmented views of the same input as a positive pair.
- **MoCo** uses momentum contrast.
- **SimSiam** learns Siamese representations without labels.
- **BYOL** uses online and target networks for bootstrap learning.
- **VICReg** combines invariance with variance and covariance regularization to avoid collapse.
- **DINO** and **iBOT** use teacher/student vision-transformer training; centering the teacher output helps prevent collapse.

## Implementation reference

The lecture recommends PyTorch Metric Learning, which includes ArcFace, contrastive, CosFace, N-pairs, NT-Xent, triplet-margin, and supervised-contrastive losses.

## Key takeaways

1. Design an embedding space where distance captures the similarity needed by the task.
2. Embeddings enable open-set recognition and nearest-neighbour retrieval.
3. Pairwise, triplet, classification-margin, and self-supervised losses shape the space in different ways.
4. Normalization, hard-example selection, margins, and temperature are important practical details.
