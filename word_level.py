from pathlib import Path
import numpy as np
import pandas as pd
import codecs
import os
import logging

import keras.backend as K
from sklearn.metrics import f1_score, precision_score, recall_score
from keras.layers import Input, Embedding, Lambda, Dense
from keras.models import Model
from keras.optimizers import Adam
from keras.callbacks import Callback, EarlyStopping

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


ROOT = Path("./data")
MODEL_SAVED = Path("./model_saved")
OUTPUT = Path("./output")

if not os.path.exists(MODEL_SAVED):
    os.makedirs(MODEL_SAVED)


mode = None
np.random.seed(123)
learning_rate = 5e-3
min_learning_rate = 1e-3
binary_classifier_threshold = 0.5


categories = ["aids", "breast_cancer", "diabetes", "hepatitis", "hypertension"]


data = []
for index, row in pd.read_csv(ROOT / "train.csv").iterrows():
    data.append(
        (row['question1'],
         row['question2'],
         row['category'],
         row['label']))

test_data = []
for index, row in pd.read_csv(ROOT / "dev_id.csv").iterrows():
    test_data.append(
        (row['question1'],
         row['question2'],
         row['category'],
         row['id']))


class Evaluator(Callback):
    def __init__(self, model_name, valid_ds):
        super(Evaluator, self).__init__()
        self._best_f1 = 0.
        self.passed = 0
        self._model_saved = MODEL_SAVED / model_name
        self.valid_ds = valid_ds
        if not os.path.exists(self._model_saved):
            os.makedirs(self._model_saved)

    def on_epoch_begin(self, epoch, logs=None):
        if self.passed < self.params['steps']:
            lr = (self.passed + 1.) / self.params['steps'] * learning_rate
            K.set_value(self.model.optimizer.lr, lr)
            self.passed += 1
        elif self.params['steps'] <= self.passed < self.params['steps'] * 2:
            lr = (2 - (self.passed + 1.) /
                  self.params['steps']) * (learning_rate - min_learning_rate)
            lr += min_learning_rate
            K.set_value(self.model.optimizer.lr, lr)
            self.passed += 1

    def on_epoch_end(self, epoch, logs=None):
        val_predict = (
            np.asarray(
                self.model.predict_generator(
                    self.valid_ds.iterator(),
                    steps=len(self.valid_ds))))
        val_predict = np.squeeze(val_predict)
        for i in range(len(val_predict)):
            if val_predict[i] >= binary_classifier_threshold:
                val_predict[i] = 1.0
            else:
                val_predict[i] = 0.0
        val_targ = self.valid_ds.all_labels
        _val_f1 = f1_score(val_targ, val_predict)
        _val_recall = recall_score(val_targ, val_predict)
        _val_precision = precision_score(val_targ, val_predict)
        print("One epoch ended, evaluator hook is called")
        print("-val_f1_measure: ", round(_val_f1, 4),
              "\t-val_p_measure: ", round(_val_precision, 4),
              "\t-val_r_measure: ", round(_val_recall, 4))
        if _val_f1 > self._best_f1:
            assert isinstance(mode, int), "check mode, must be a integer"
            file_names = os.listdir(self._model_saved)
            for fn in file_names:
                if "mode_%s" % str(mode) in fn:
                    logger.info(
                        "Delete %s from %s" %
                        ((self._model_saved / fn).name, self._model_saved))
                    os.remove(self._model_saved / fn)

            logger.info(
                "Write %s into %s" %
                ("mode_%s_F1_%s.weights" %
                 (str(mode), str(
                     round(
                         _val_f1, 4))), self._model_saved))
            self.model.save_weights(self._model_saved /
                                    ("mode_%s_F1_%s.weights" %
                                     (str(mode), str(round(_val_f1, 4)))))
            self._best_f1 = _val_f1


class DataGenerator:
    def __init__(self, data, batch_size=32, test=False):
        self.data = data
        self.batch_size = batch_size
        self.steps = len(self.data) // self.batch_size
        if len(self.data) % self.batch_size != 0:
            self.steps += 1
        self.test = test

        if not test:
            logger.info("__Shuffle the dataset__")
            self.idxs = [x for x in range(len(self.data))]
            np.random.shuffle(self.idxs)
            self.all_labels = self._get_all_label_as_ndarray()
            self.all_labels = self.all_labels[self.idxs]
        else:
            self.ID = self._get_all_id_as_ndarray()

    def __len__(self):
        return self.steps

    def iterator(self):
        while True:
            if not self.test:
                raise NotImplementedError
            elif self.test:
                raise NotImplementedError

    def _get_all_label_as_ndarray(self):
        if self.test:
            return None
        all_labels = []
        for x in self.data:
            all_labels.append(x[-1])
        return np.array(all_labels, dtype=np.float32)

    def _get_all_id_as_ndarray(self):
        if not self.test:
            return None
        all_ids = []
        for x in self.data:
            all_ids.append(x[-1])
        return np.array(all_ids, dtype=np.int32)


def create_esim_model() -> [Model, Model]:
    raise NotImplementedError


def seq_padding(seqs, padding=0):
    lens = [len(x)for x in seqs]
    max_len = max(lens)
    return np.array([np.concatenate([x, [padding] * (max_len - len(x))])
                     if len(x) < max_len else x for x in seqs])


def train(train_model, train_ds, valid_ds, model_name):

    evaluator = Evaluator(model_name=model_name, valid_ds=valid_ds)
    early_stopping = EarlyStopping(monitor='val_loss', patience=10, verbose=1)

    train_model.fit_generator(train_ds.iterator(),
                              steps_per_epoch=len(train_ds),
                              epochs=50,
                              validation_data=valid_ds.iterator(),
                              validation_steps=len(valid_ds),
                              callbacks=[evaluator, early_stopping])


def predict(model, weights_path, test_ds, valid_result_name, valid_logits_name):
    model.load_weights(weights_path)
    probs = model.predict_generator(test_ds.iterator(), steps=len(test_ds))
    probs = np.squeeze(probs)

    preds = []

    for i in range(len(probs)):
        if probs[i] > binary_classifier_threshold:
            preds.append(1)
        else:
            preds.append(0)
    preds = np.array(preds, dtype=np.int32)

    ids = test_ds.ID

    _valid_result = pd.DataFrame({"id": ids, "label": preds})
    _valid_logits = pd.DataFrame({"id": ids, "logits": probs})

    _valid_result.to_csv(
        OUTPUT / valid_result_name,
        index=False)
    _valid_logits.to_csv(
        OUTPUT / valid_logits_name,
        index=False)


def gen_stacking_features(weights_root_path, model_name):
    valid_true_labels = []
    valid_probs = []
    mode_test_ds = DataGenerator(test_data, batch_size=32, test=True)
    test_ids = mode_test_ds.ID
    test_probs = []
    for weight in os.listdir(weights_root_path):
        _mode = int(weight.split('_')[1])
        train_model, _ = create_esim_model()  # todo: be easy to modify it
        train_model.load_weights(weights_root_path / weight)

        _valid_data = [
            data[j] for i,
            j in enumerate(random_order) if i %
            10 == _mode]

        mode_valid_ds = DataGenerator(_valid_data, batch_size=32, test=False)
        valid_true_labels.append(mode_valid_ds.all_labels)

        valid_probs.append(
            np.squeeze(
                train_model.predict_generator(
                    mode_valid_ds.iterator(),
                    steps=len(mode_valid_ds))))

        K.clear_session()

        # todo: the next is to deal with the abundant calling
        _, model = create_esim_model()
        model.load_weights(weights_root_path / weight)
        test_probs.append(
            np.squeeze(
                model.predict_generator(
                    mode_test_ds.iterator(),
                    steps=len(mode_test_ds))))

        K.clear_session()

    to_vote_format = {"id": test_ids}
    for i, each in enumerate(test_probs):
        to_vote_format["label_%s" % str(i)] = np.array(each.round(), np.int32)
    pd.DataFrame(to_vote_format).to_csv(ROOT / (model_name + "_predictions_for_vote.csv"), index=False)

    valid_out = pd.DataFrame({"probs": np.concatenate(
        valid_probs), "label": np.array(np.concatenate(valid_true_labels), np.int32)})

    test_out = pd.DataFrame(
        {"id": test_ids, "probs": np.mean(test_probs, axis=0)})

    valid_out.to_csv(ROOT / (model_name + "_stacking_new_train.csv"),
                     index=False)  # todo: be easy to modify it
    test_out.to_csv(
        ROOT / (model_name + "_stacking_new_test.csv"), index=False)


if __name__ == "__main__":
    # 按照9:1的比例划分训练集和验证集
    random_order = [x for x in range(len(data))]
    np.random.shuffle(random_order)

    for mode in range(10):
        train_data = [
            data[j] for i,
            j in enumerate(random_order) if i %
            10 != mode]
        valid_data = [
            data[j] for i,
            j in enumerate(random_order) if i %
            10 == mode]

        _train_ds = DataGenerator(train_data, batch_size=32, test=False)
        _valid_ds = DataGenerator(valid_data, batch_size=32, test=False)

        _test_ds = DataGenerator(test_data, batch_size=32, test=True)

        _train_model, _model = create_esim_model()

        train(
            train_model=_train_model,
            train_ds=_train_ds,
            valid_ds=_valid_ds,
            model_name="base_esim")
        logger.info("___Reset The Computing Graph___")
        K.clear_session()
    gen_stacking_features(Path(MODEL_SAVED) / "base_esim", "base_esim")