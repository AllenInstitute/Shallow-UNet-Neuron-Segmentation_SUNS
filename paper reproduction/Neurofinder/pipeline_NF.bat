python "C:\Matlab Files\timer\timer_start_next_2.py"
REM REM Training pipeline
REM python train_CNN_params_NF_noSF_2skip.py

REM REM Run SUNS batch
REM python test_batch_NF_noSF_2skip.py
REM REM Run SUNS online
REM python test_online_NF_noSF_2skip.py
REM python test_online_NF_noSF_2skip_update.py

REM python train_CNN_params_NF_noSF_vary_CNN.py 3 4 [1] elu True 1skip 0 noSF
REM python test_online_NF_noSF_2skip.py
REM python test_online_NF_noSF_2skip_update.py
REM python test_batch_NF_noSF_vary_CNN.py 3 4 [1] elu True 1skip 0 noSF
REM python test_online_NF_noSF_2skip.py
REM python test_online_NF_noSF_2skip_update.py
REM python test_batch_NF_noSF_vary_CNN.py 3 4 [1] elu True 1skip 0 noSF
REM python train_CNN_params_NF_noSF_vary_CNN.py 3 4 [1,2] elu True 2skip 0 noSF
REM python test_batch_NF_noSF_vary_CNN.py 3 4 [1,2] elu True 2skip 0 noSF
REM python train_CNN_params_NF_noSF_vary_CNN.py 3 4 [1] elu True 1skip 1 noSF_subtract
REM python test_online_NF_noSF_2skip_update.py
REM python test_batch_NF_noSF_vary_CNN.py 3 4 [1] elu True 1skip 1 noSF_subtract
REM python test_online_NF_noSF_2skip.py
REM python test_online_NF_noSF_2skip_update.py
REM python train_CNN_params_NF_noSF_vary_CNN.py 3 4 [1,2] elu True 2skip 0 noSF
python test_batch_NF_noSF_vary_CNN.py 3 4 [1,2] elu True 2skip 0 noSF
REM python test_online_NF_noSF_2skip.py
REM python test_online_NF_noSF_2skip_update.py
REM python train_CNN_params_NF_noSF_vary_CNN.py 3 4 [1,2] elu True 2skip 1 noSF_subtract
python test_batch_NF_noSF_vary_CNN.py 3 4 [1,2] elu True 2skip 1 noSF_subtract
REM python test_online_NF_noSF_2skip_copy.py
REM python test_online_NF_noSF_2skip_update_copy.py
python "C:\Matlab Files\timer\timer_stop.py"
