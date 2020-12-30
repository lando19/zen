#ifndef TX_CREATION_UTILS_H
#define TX_CREATION_UTILS_H

#include <primitives/transaction.h>
#include <primitives/certificate.h>

namespace txCreationUtils
{
CMutableTransaction populateTx(int txVersion,
                               const CAmount & creationTxAmount = CAmount(0),
                               const CAmount & fwdTxAmount = CAmount(0),
                               int epochLength = 5);
void signTx(CMutableTransaction& mtx);

CTransaction createNewSidechainTxWith(const CAmount & creationTxAmount, int epochLength = 15);
CTransaction createFwdTransferTxWith(const uint256 & newScId, const CAmount & fwdTxAmount);

CTransaction createCoinBase(const CAmount& amount);
CTransaction createTransparentTx(bool ccIsNull = true); //ccIsNull = false allows generation of faulty tx with non-empty cross chain output
CTransaction createSproutTx(bool ccIsNull = true); //ccIsNull = false allows generation of faulty tx with non-empty cross chain output

void extendTransaction(CTransaction & tx, const uint256 & scId, const CAmount & amount);

CScCertificate createCertificate(const uint256 & scId, int epochNum, const uint256 & endEpochBlockHash,
                                 CAmount changeTotalAmount/* = 0*/, unsigned int numChangeOut/* = 0*/,
                                 CAmount bwtTotalAmount/* = 1*/, unsigned int numBwt/* = 1*/);

uint256 CreateSpendableCoinAtHeight(CCoinsViewCache& targetView, unsigned int coinHeight);
} // end of namespace

namespace chainSettingUtils
{
    void ExtendChainActiveToHeight(int targetHeight);
    void ExtendChainActiveWithBlock(const CBlock& block);
} // end of namespace

#endif
